from unittest.mock import MagicMock

from app.ai.brief import BriefResult, save_brief
from app.ai.guard import GuardResult


def test_save_brief_writes_body_and_guard():
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 7
    result = BriefResult(body="# Brief", source="llm", guard=GuardResult(ok=True, checked=12))

    assert save_brief(session, result, period_days=7) == 7

    params = session.execute.call_args.args[1]
    assert params == {
        "period_days": 7,
        "source": "llm",
        "body": "# Brief",
        "guard_ok": True,
        "guard_checked": 12,
    }


def test_save_deterministic_brief():
    session = MagicMock()
    save_brief(session, BriefResult(body="x", source="deterministic"), period_days=7)
    params = session.execute.call_args.args[1]
    assert params["guard_ok"] is None
    assert params["source"] == "deterministic"
