"""Question answering over the warehouse figures.

Same contract as the brief: the model gets a closed set of numbers, never a database
connection. It cannot run a query, so it cannot quietly widen the question, and every
figure it writes back is checked against the payload it was given. An answer containing a
number the warehouse cannot account for is refused rather than shown.

That refusal is the point. In a pricing context a confident sentence carrying an invented
figure is worse than no answer, because someone acts on it. The worst case here is "I
cannot answer that from the data", which is true.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.facts import collect_weekly_facts
from app.ai.guard import validate_brief
from app.ai.llm import BudgetExhausted, build_llm, reserve
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

MAX_QUESTION_CHARS = 500

SYSTEM_PROMPT = """
You answer questions about a competitor price-intelligence warehouse for a retail
category team.

ABSOLUTE CONSTRAINT: you may only state numbers that appear in the FACTS JSON below.
Do not round them, do not average them, do not compute new figures, do not add,
subtract or convert them, and do not estimate. If answering would require a number that
is not in the FACTS, say plainly that the data does not contain it and stop.

Scope: only this dataset. If asked about anything else -- general knowledge, other
companies, opinions, what you are -- reply that you can only answer questions about this
pricing data.

Be brief: two or three sentences, no preamble, no bullet lists unless the question asks
for several items. Where a figure rests on stale evidence or very few observations, say
so rather than presenting it as solid.

FACTS:
{facts_json}

QUESTION:
{question}
"""

REFUSAL = (
    "I could not answer that from the data without using a figure the warehouse cannot "
    "account for, so I have not answered rather than risk an invented number."
)


@dataclass
class ChatAnswer:
    answer: str
    ok: bool = True
    source: str = "llm"  # "llm" | "refused" | "unavailable"
    checked: int = 0
    unsupported: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "answer": self.answer,
            "ok": self.ok,
            "source": self.source,
            "checked": self.checked,
            "unsupported": [str(u) for u in self.unsupported],
        }


def answer_question(session: Session, question: str, period_days: int = 7) -> ChatAnswer:
    """Answer one question about the data, or decline.

    Never raises. Every failure path -- no model, no allowance, a provider outage, a
    guard rejection -- returns a `ChatAnswer` saying what happened, because this is
    wired to a text box on a page and an exception there is just a blank panel.
    """
    question = (question or "").strip()
    if not question:
        return ChatAnswer("Ask a question about the pricing data.", ok=False, source="refused")
    if len(question) > MAX_QUESTION_CHARS:
        return ChatAnswer(
            f"That question is longer than {MAX_QUESTION_CHARS} characters. "
            "Shorter questions get better answers, and cost less of the daily allowance.",
            ok=False,
            source="refused",
        )

    settings = get_settings()
    if not settings.llm_model:
        return ChatAnswer(
            "No language model is configured, so questions cannot be answered. "
            "The figures themselves are all on this page and in the API.",
            ok=False,
            source="unavailable",
        )

    facts = collect_weekly_facts(session, period_days=period_days)
    facts_json = json.dumps(facts.as_dict(), indent=2, default=str)

    try:
        from app.ai.crew import _require_llm, _silence_crewai_prompts  # noqa: PLC0415

        model = _require_llm()
        _silence_crewai_prompts()
        reserve(1, settings)

        llm = build_llm(model, settings)
        raw = str(llm.call(SYSTEM_PROMPT.format(facts_json=facts_json, question=question)))
    except BudgetExhausted as exc:
        log.warning("chat.budget_exhausted", error=str(exc))
        return ChatAnswer(
            f"The daily model allowance is spent ({exc}). The figures on this page are "
            "unaffected -- they come from the warehouse, not the model.",
            ok=False,
            source="unavailable",
        )
    except Exception as exc:  # noqa: BLE001 - a chat box must not surface a stack trace
        log.warning("chat.unavailable", error=str(exc)[:200])
        return ChatAnswer(
            "The model could not be reached just now. Try again in a moment.",
            ok=False,
            source="unavailable",
        )

    # The same guard the weekly brief uses. An answer is only shown if every number in
    # it came from the payload the model was given.
    guard = validate_brief(raw, facts.all_numbers())
    if not guard.ok:
        log.error("chat.rejected", question=question[:120], unsupported=guard.unsupported)
        return ChatAnswer(
            REFUSAL,
            ok=False,
            source="refused",
            checked=guard.checked,
            unsupported=list(guard.unsupported),
        )

    log.info("chat.answered", checked=guard.checked)
    return ChatAnswer(raw.strip(), ok=True, source="llm", checked=guard.checked)
