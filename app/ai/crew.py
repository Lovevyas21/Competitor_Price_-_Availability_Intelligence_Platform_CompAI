"""CrewAI crew for narrating the weekly brief.

Role split follows the build document: an analyst reads the numbers, a forecast
interpreter explains direction and confidence, a writer composes the brief.

One deliberate departure from the obvious design: **the writer is given a facts payload,
not a database tool.** The build document suggests a read-only SQL tool for the analyst,
and `tools.py` provides one for exploration -- but the drafting path deliberately does
not use it. An agent that can query freely can also summarise loosely, and its output is
then unverifiable. Handing it a closed set of numbers makes `guard.validate_brief` a
decidable check rather than a guess.

CrewAI and an LLM key are both optional. Without them the brief renders deterministically
(see `brief.py`), which is the default.
"""

from __future__ import annotations

import json
import os
import time

from app.ai.facts import WeeklyFacts
from app.ai.llm import build_llm, reserve
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


class CrewUnavailable(RuntimeError):
    """Raised when CrewAI or an LLM credential is not configured."""


WRITER_INSTRUCTIONS = """
You are writing a weekly competitor-pricing brief for a category manager.

ABSOLUTE CONSTRAINT: you may only state numbers that appear in the FACTS JSON below.
Do not round them, do not average them, do not compute new figures, do not estimate.
If a number you want is not in the FACTS, leave it out and describe the situation
qualitatively instead.

Write in plain British English. Be direct and short: what changed, who is undercutting
us, what deserves attention this week. No preamble, no filler, no invented context.
Use Markdown with a heading and short sections.

FACTS:
{facts_json}
"""

#: The single-call prompt. It carries the same absolute numeric constraint as the crew
#: version, plus the two judgements the analyst and interpreter agents used to contribute:
#: rank by what changes a decision, and refuse to sound confident about thin accuracy
#: figures. Those were instructions, not information -- which is why they fold into one
#: prompt without losing anything.
SINGLE_CALL_INSTRUCTIONS = """
You are writing a weekly competitor-pricing brief for a category manager.

ABSOLUTE CONSTRAINT: you may only state numbers that appear in the FACTS JSON below.
Do not round them, do not average them, do not compute new figures, do not estimate.
If a number you want is not in the FACTS, leave it out and describe the situation
qualitatively instead.

Select ruthlessly. Lead with the two or three findings that would change a pricing
decision this week, not with everything present. An undercut computed from stale
evidence is not urgent -- say so rather than implying action is needed.

Where you mention forecasts, state what their accuracy actually supports. If the error
figures rest on few series, say that plainly instead of projecting confidence.

Write in plain British English. Be direct and short: what changed, who is undercutting
us, what deserves attention. No preamble, no filler, no invented context. Use Markdown
with a heading and short sections, and end each section with a one-line decision.

FACTS:
{facts_json}
"""


#: LiteLLM model prefix -> (settings field, every environment variable that provider
#: might read). Gemini has two, and the google-genai client prefers GOOGLE_API_KEY when
#: both are present -- so both must be set to the same value or the wrong one silently
#: wins. That is not hypothetical: an unrelated GOOGLE_API_KEY left in a developer's
#: environment sent every request out on a stranger's quota, and the resulting stream of
#: 503s looked exactly like the model being busy.
PROVIDER_KEYS = {
    "gemini/": ("gemini_api_key", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    "openai/": ("openai_api_key", ("OPENAI_API_KEY",)),
    "anthropic/": ("anthropic_api_key", ("ANTHROPIC_API_KEY",)),
}


def _require_llm() -> str:
    """Return the configured model id, having put its credential where LiteLLM looks.

    The bridge matters: configuration lives in `.env` and is read by pydantic-settings,
    which populates `Settings` and deliberately does *not* touch `os.environ`. LiteLLM,
    underneath CrewAI, reads only `os.environ`. Without this, a key set correctly in
    `.env` is invisible to the model call, and the failure surfaces as a provider
    authentication error that points nowhere near the actual cause.

    A key configured here wins over one already in the environment, and is written to
    every variable the provider might consult. The rule is that the credential named in
    the app's own configuration is the credential the app uses -- anything else makes
    "which key did that request go out on?" unanswerable without reading the process
    environment. When no key is configured the environment is left untouched, so a
    deployment injecting secrets that way (an EC2 task role, a CI secret) still works.
    """
    settings = get_settings()
    model = getattr(settings, "llm_model", None)
    if not model:
        raise CrewUnavailable(
            "no LLM configured; set LLM_MODEL (and the provider key) to enable narration"
        )

    for prefix, (field, env_vars) in PROVIDER_KEYS.items():
        if not model.startswith(prefix):
            continue

        key = getattr(settings, field, None)
        if key:
            for env_var in env_vars:
                os.environ[env_var] = key
        elif not any(os.environ.get(v) for v in env_vars):
            raise CrewUnavailable(
                f"LLM_MODEL is {model!r} but no credential is set; "
                f"add {env_vars[0]} to .env to enable narration"
            )
        break

    return model


#: Opt-outs applied before CrewAI is imported. Left overridable so an operator who wants
#: tracing can still switch it back on.
_QUIET_DEFAULTS = {
    "CREWAI_TRACING_ENABLED": "false",
    "CREWAI_TELEMETRY_OPT_OUT": "true",
    "OTEL_SDK_DISABLED": "true",
}


def _silence_crewai_prompts() -> None:
    """Stop CrewAI asking the terminal a question mid-run.

    On first use CrewAI prints a tracing offer and waits on stdin for 20 seconds. That is
    merely annoying from a shell, but this brief is also a scheduled Celery task, where
    there is no one to answer and the prompt is pure dead time. Its telemetry exporter
    then blocks on an unreachable collector, which is another stall for a feature nobody
    asked for here.
    """
    for name, value in _QUIET_DEFAULTS.items():
        os.environ.setdefault(name, value)


def _narrate_single(facts_json, llm, model, Agent, Crew, Process, Task) -> str:
    """One writer, one request, one copy of the facts.

    The writer in the full crew already receives the complete payload; the analyst and
    interpreter refine emphasis rather than supply information it lacks. Folding their
    briefs into the writer's instructions keeps that emphasis at a third of the cost.
    """
    writer = Agent(
        role="Pricing analyst and brief writer",
        goal="Write the weekly pricing brief using only the supplied facts.",
        backstory=(
            "You review competitor pricing for a retail category team. You cut a wall of "
            "numbers down to the two or three that change a decision, you say plainly "
            "when accuracy figures are too thin to support a confident claim, and you "
            "never invent a figure."
        ),
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )

    task = Task(
        description=SINGLE_CALL_INSTRUCTIONS.format(facts_json=facts_json),
        expected_output="A Markdown weekly pricing brief citing only the supplied numbers.",
        agent=writer,
    )

    crew = Crew(agents=[writer], tasks=[task], process=Process.sequential, verbose=False)
    log.info("brief.crew_start", model=model, mode="single")
    return _kickoff_with_retry(crew, model)


def narrate_with_crew(facts: WeeklyFacts) -> str:
    """Turn the facts payload into prose. Raises CrewUnavailable when not configured.

    Runs as a single writer call by default. The three-agent crew below is the design the
    build document describes and is kept intact behind `llm_single_call=False`, but it
    costs three requests and three copies of the facts payload to produce a brief the
    writer can produce alone -- which on a free-tier key is most of a day's allowance for
    a difference in wording.
    """
    model = _require_llm()
    settings = get_settings()

    _silence_crewai_prompts()

    try:
        from crewai import Agent, Crew, Process, Task  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise CrewUnavailable("crewai is not installed; pip install -e '.[ai]'") from exc

    facts_json = json.dumps(facts.as_dict(), indent=2, default=str)
    llm = build_llm(model, settings)

    if settings.llm_single_call:
        reserve(1, settings)
        return _narrate_single(facts_json, llm, model, Agent, Crew, Process, Task)

    reserve(3, settings)

    analyst = Agent(
        role="Pricing analyst",
        goal="Identify the few things in this week's pricing data that actually matter.",
        backstory=(
            "You review competitor pricing for a retail category team. You are known for "
            "cutting a wall of numbers down to the two or three that change a decision."
        ),
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )

    interpreter = Agent(
        role="Forecast interpreter",
        goal="Explain what the forecasts and their error rates justify claiming.",
        backstory=(
            "You translate model output into plain language, and you are careful to say "
            "when the accuracy figures are too thin to support a confident statement."
        ),
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )

    writer = Agent(
        role="Brief writer",
        goal="Write the weekly pricing brief using only the supplied facts.",
        backstory=(
            "You write short internal briefs. You never invent a figure; if a number is "
            "not in front of you, you describe the situation without it."
        ),
        allow_delegation=False,
        verbose=False,
        llm=llm,
    )

    analysis = Task(
        description=(
            "From the FACTS below, pick the most decision-relevant undercuts and price "
            "movements. Quote figures exactly as given.\n\n" + facts_json
        ),
        expected_output="A short bullet list of the findings that matter, with exact figures.",
        agent=analyst,
    )

    interpretation = Task(
        description=(
            "Using the forecast summary and accuracy figures in the FACTS, state what the "
            "forecasts support. If accuracy is based on few points, say so plainly.\n\n"
            + facts_json
        ),
        expected_output="Two or three sentences on forecast direction and confidence.",
        agent=interpreter,
    )

    writing = Task(
        description=WRITER_INSTRUCTIONS.format(facts_json=facts_json),
        expected_output="A Markdown weekly pricing brief citing only the supplied numbers.",
        agent=writer,
        context=[analysis, interpretation],
    )

    crew = Crew(
        agents=[analyst, interpreter, writer],
        tasks=[analysis, interpretation, writing],
        process=Process.sequential,
        verbose=False,
    )

    log.info("brief.crew_start", model=model, mode="crew")
    return _kickoff_with_retry(crew, model)


#: Transient upstream conditions worth a second attempt. A hosted model returning "busy"
#: is the normal case, not an exceptional one: measured against gemini-3.8-flash, roughly
#: one call in three came back 503 while the same prompt succeeded moments later.
_RETRYABLE = ("503", "429", "unavailable", "overloaded", "high demand", "rate limit")

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 4.0


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _RETRYABLE)


def _kickoff_with_retry(crew, model: str) -> str:
    """Run the crew, retrying transient provider failures with a widening backoff.

    Without this a momentarily busy model silently demotes the brief to its deterministic
    form -- correct output, but the narration quietly stops happening and nobody notices,
    because the fallback is indistinguishable from success unless you read the log.

    Only transient conditions are retried. A bad key or an unknown model fails on the
    first attempt, where the error still means something.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return str(crew.kickoff())
        except Exception as exc:
            if attempt == MAX_ATTEMPTS or not _is_retryable(exc):
                raise
            delay = BACKOFF_SECONDS * attempt
            log.warning(
                "brief.crew_retry",
                model=model,
                attempt=attempt,
                of=MAX_ATTEMPTS,
                sleeping=delay,
                error=str(exc)[:200],
            )
            time.sleep(delay)

    raise CrewUnavailable("unreachable")  # pragma: no cover - loop always returns or raises
