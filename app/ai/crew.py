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

from app.ai.facts import WeeklyFacts
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


def _require_llm() -> str:
    """Return the configured model id, or explain what is missing."""
    settings = get_settings()
    model = getattr(settings, "llm_model", None)
    if not model:
        raise CrewUnavailable(
            "no LLM configured; set LLM_MODEL (and the provider key) to enable narration"
        )
    return model


def narrate_with_crew(facts: WeeklyFacts) -> str:
    """Turn the facts payload into prose. Raises CrewUnavailable when not configured."""
    model = _require_llm()

    try:
        from crewai import Agent, Crew, Process, Task  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise CrewUnavailable("crewai is not installed; pip install -e '.[ai]'") from exc

    facts_json = json.dumps(facts.as_dict(), indent=2, default=str)

    analyst = Agent(
        role="Pricing analyst",
        goal="Identify the few things in this week's pricing data that actually matter.",
        backstory=(
            "You review competitor pricing for a retail category team. You are known for "
            "cutting a wall of numbers down to the two or three that change a decision."
        ),
        allow_delegation=False,
        verbose=False,
        llm=model,
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
        llm=model,
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
        llm=model,
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

    log.info("brief.crew_start", model=model)
    return str(crew.kickoff())
