import json
import os
import time

from app.ai.facts import WeeklyFacts
from app.ai.llm import build_llm, reserve
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


class CrewUnavailable(RuntimeError):
    pass


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


PROVIDER_KEYS = {
    "gemini/": ("gemini_api_key", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    "openai/": ("openai_api_key", ("OPENAI_API_KEY",)),
    "anthropic/": ("anthropic_api_key", ("ANTHROPIC_API_KEY",)),
}


def _require_llm() -> str:
    settings = get_settings()
    model = getattr(settings, "llm_model", None)
    if not model:
        raise CrewUnavailable("LLM_MODEL not set")

    for prefix, (field, env_vars) in PROVIDER_KEYS.items():
        if not model.startswith(prefix):
            continue

        key = getattr(settings, field, None)
        if key:
            for env_var in env_vars:
                os.environ[env_var] = key
        elif not any(os.environ.get(v) for v in env_vars):
            raise CrewUnavailable(f"no API key for {model}, set {env_vars[0]}")
        break

    return model


_QUIET_DEFAULTS = {
    "CREWAI_TRACING_ENABLED": "false",
    "CREWAI_TELEMETRY_OPT_OUT": "true",
    "OTEL_SDK_DISABLED": "true",
}


def _silence_crewai_prompts() -> None:
    for name, value in _QUIET_DEFAULTS.items():
        os.environ.setdefault(name, value)


def _narrate_single(facts_json, llm, model, Agent, Crew, Process, Task) -> str:
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
    model = _require_llm()
    settings = get_settings()

    _silence_crewai_prompts()

    try:
        from crewai import Agent, Crew, Process, Task
    except ImportError as exc:
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


_RETRYABLE = ("503", "429", "unavailable", "overloaded", "high demand", "rate limit")

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 4.0


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _RETRYABLE)


def _kickoff_with_retry(crew, model: str) -> str:
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

    raise CrewUnavailable("unreachable")
