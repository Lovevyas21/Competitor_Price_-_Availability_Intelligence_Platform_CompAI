from unittest.mock import MagicMock, patch

import pytest

from app.ai import chat
from app.ai.llm import BudgetExhausted
from app.core.settings import Settings

FACTS = {
    "totals": {"active_undercuts": 108, "products_tracked": 3932},
    "top_undercuts": [{"retailer_name": "EDEKA", "competitor_price": 3.29, "gap_pct": -42.58}],
}


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, llm_model="gemini/gemini-3.5-flash", **kw)


def _facts_obj():
    facts = MagicMock()
    facts.as_dict.return_value = FACTS
    facts.all_numbers.return_value = {108.0, 3932.0, 3.29, -42.58, 42.58}
    return facts


def _run(model_says: str, settings: Settings | None = None) -> chat.ChatAnswer:
    llm = MagicMock()
    llm.call.return_value = model_says
    with (
        patch.object(chat, "get_settings", return_value=settings or _settings()),
        patch.object(chat, "collect_weekly_facts", return_value=_facts_obj()),
        patch("app.ai.crew._require_llm", return_value="gemini/gemini-3.5-flash"),
        patch("app.ai.crew._silence_crewai_prompts"),
        patch.object(chat, "reserve"),
        patch.object(chat, "build_llm", return_value=llm),
    ):
        return chat.answer_question(MagicMock(), "who undercuts us most?")


def test_invented_figure_refused():
    answer = _run("EDEKA undercuts us by 91.4%, costing us 12000 EUR this quarter.")
    assert answer.ok is False
    assert answer.source == "refused"
    assert answer.answer == chat.REFUSAL
    assert answer.unsupported


def test_grounded_answer():
    answer = _run("EDEKA is cheapest at 3.29 EUR, a gap of -42.58%. There are 108 undercuts.")
    assert answer.ok is True
    assert answer.source == "llm"
    assert answer.checked >= 3
    assert answer.unsupported == []


def test_qualitative_answer():
    answer = _run("The data does not contain a figure for that.")
    assert answer.ok is True
    assert answer.checked == 0


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_empty_question(question):
    with patch.object(chat, "build_llm") as build:
        answer = chat.answer_question(MagicMock(), question)
    assert answer.ok is False
    build.assert_not_called()


def test_question_too_long():
    with patch.object(chat, "build_llm") as build:
        answer = chat.answer_question(MagicMock(), "x" * (chat.MAX_QUESTION_CHARS + 1))
    assert answer.ok is False
    assert str(chat.MAX_QUESTION_CHARS) in answer.answer
    build.assert_not_called()


def test_no_model_configured_says_so_plainly():
    with patch.object(chat, "get_settings", return_value=Settings(_env_file=None, llm_model=None)):
        answer = chat.answer_question(MagicMock(), "anything?")
    assert answer.source == "unavailable"
    assert answer.ok is False


def test_budget_spent():
    llm = MagicMock()
    with (
        patch.object(chat, "get_settings", return_value=_settings()),
        patch.object(chat, "collect_weekly_facts", return_value=_facts_obj()),
        patch("app.ai.crew._require_llm", return_value="gemini/x"),
        patch("app.ai.crew._silence_crewai_prompts"),
        patch.object(chat, "reserve", side_effect=BudgetExhausted("daily allowance spent")),
        patch.object(chat, "build_llm", return_value=llm),
    ):
        answer = chat.answer_question(MagicMock(), "who undercuts us?")

    assert answer.source == "unavailable"
    assert "unaffected" in answer.answer
    llm.call.assert_not_called()


def test_provider_outage():
    llm = MagicMock()
    llm.call.side_effect = RuntimeError("503 UNAVAILABLE high demand")
    with (
        patch.object(chat, "get_settings", return_value=_settings()),
        patch.object(chat, "collect_weekly_facts", return_value=_facts_obj()),
        patch("app.ai.crew._require_llm", return_value="gemini/x"),
        patch("app.ai.crew._silence_crewai_prompts"),
        patch.object(chat, "reserve"),
        patch.object(chat, "build_llm", return_value=llm),
    ):
        answer = chat.answer_question(MagicMock(), "who undercuts us?")

    assert answer.source == "unavailable"
    assert "503" not in answer.answer
    assert "Traceback" not in answer.answer


def test_prompt_limits_scope():
    assert "ABSOLUTE CONSTRAINT" in chat.SYSTEM_PROMPT
    assert "only this dataset" in chat.SYSTEM_PROMPT
    assert "{facts_json}" in chat.SYSTEM_PROMPT


def test_answer_serialises():
    answer = chat.ChatAnswer("hello", checked=3)
    assert answer.as_dict() == {
        "answer": "hello",
        "ok": True,
        "source": "llm",
        "checked": 3,
        "unsupported": [],
    }


def test_definition_answer():
    answer = _run(
        "A critical undercut is a competitor price 20% or more below ours. "
        "EDEKA is one, at -42.58%."
    )
    assert answer.ok is True
    assert answer.unsupported == []


def test_rounded_figure_allowed():
    answer = _run("EDEKA undercuts us by about 42.6%, at 3.29 EUR.")
    assert answer.ok is True


def test_prompt_has_definitions():
    assert "{definitions_json}" in chat.SYSTEM_PROMPT
    assert "critical" in chat.DEFINITIONS["undercut_severity"]
