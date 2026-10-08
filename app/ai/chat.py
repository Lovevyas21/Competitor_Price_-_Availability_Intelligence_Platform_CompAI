import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.facts import collect_weekly_facts, numbers_in
from app.ai.guard import validate_brief
from app.ai.llm import BudgetExhausted, build_llm, reserve
from app.ai.matching import AUTO_MATCH_THRESHOLD, REVIEW_THRESHOLD
from app.alerting.service import MAX_ALERTABLE_STALENESS_DAYS
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.forecasting.dataset import MAX_STALENESS_DAYS, MIN_OBSERVATIONS
from app.forecasting.train import CONFIDENCE_LEVEL, DEFAULT_HORIZON

log = get_logger(__name__)

MAX_QUESTION_CHARS = 500

DEFINITIONS = {
    "undercut": "a competitor selling the same product, in the same currency, below our price",
    "undercut_severity": {
        "critical": "competitor price 20% or more below ours",
        "high": "competitor price 10% to 20% below ours",
        "medium": "competitor price less than 10% below ours",
    },
    "evidence_confidence": {
        "fresh": "competitor price seen within the last 1 day",
        "recent": "competitor price seen within the last 7 days",
        "stale": "competitor price last seen more than 7 days ago",
    },
    "alerting": (
        f"an alert is sent only when the evidence is at most {MAX_ALERTABLE_STALENESS_DAYS} "
        "days old; the same undercut is not re-sent within a day, but a deeper cut is"
    ),
    "volatility": (
        "coefficient of variation (standard deviation / mean) of daily prices; "
        "0.20 or more is high, 0.05 to 0.20 is medium, below that is low"
    ),
    "forecast": (
        f"{DEFAULT_HORIZON}-day price forecast per product and retailer with a "
        f"{CONFIDENCE_LEVEL}% interval, model chosen by backtested MAPE; a series needs "
        f"{MIN_OBSERVATIONS} observations and a price seen within {MAX_STALENESS_DAYS} days"
    ),
    "product_matching": (
        f"similarity {AUTO_MATCH_THRESHOLD} or higher is matched automatically, "
        f"{REVIEW_THRESHOLD} to {AUTO_MATCH_THRESHOLD} goes to human review, "
        f"below {REVIEW_THRESHOLD} is rejected"
    ),
}

SYSTEM_PROMPT = """
You answer questions about a competitor price-intelligence warehouse for a retail
category team.

Answer the question that was asked, directly, in your first sentence.
- If it asks what a term means, define it using DEFINITIONS. Add at most one example
  from FACTS, and only if it helps.
- If it asks for figures, give the figures that answer it, not everything nearby.

ABSOLUTE CONSTRAINT: every number you state must come from FACTS or DEFINITIONS. You
may round a number to one decimal place or to a whole number, but do not average,
add, subtract, convert or estimate. If answering would need a number that is in
neither, say plainly that the data does not contain it.

Scope: only this dataset. If asked about anything else (general knowledge, other
companies, opinions, what you are), reply that you can only answer questions about this
pricing data.

Be brief: two or three sentences, no preamble, no bullet lists unless the question asks
for several items. If a figure you quote rests on stale evidence or very few
observations, say so in a few words.

DEFINITIONS:
{definitions_json}

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
    source: str = "llm"
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
    definitions_json = json.dumps(DEFINITIONS, indent=2)

    try:
        from app.ai.crew import _require_llm, _silence_crewai_prompts

        model = _require_llm()
        _silence_crewai_prompts()
        reserve(1, settings)

        llm = build_llm(model, settings)
        prompt = SYSTEM_PROMPT.format(
            definitions_json=definitions_json, facts_json=facts_json, question=question
        )
        raw = str(llm.call(prompt))
    except BudgetExhausted as exc:
        log.warning("chat.budget_exhausted", error=str(exc))
        return ChatAnswer(
            f"The daily model allowance is spent ({exc}). The figures on this page are "
            "unaffected, they come from the warehouse, not the model.",
            ok=False,
            source="unavailable",
        )
    except Exception as exc:
        log.warning("chat.unavailable", error=str(exc)[:200])
        return ChatAnswer(
            "The model could not be reached just now. Try again in a moment.",
            ok=False,
            source="unavailable",
        )

    allowed = facts.all_numbers() | numbers_in(DEFINITIONS)
    guard = validate_brief(raw, allowed, allow_rounding=True)
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
