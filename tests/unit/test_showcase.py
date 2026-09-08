"""Showcase walkthrough.

Two things are worth protecting here, and neither is the animation.

The first is that the page cannot become an accidental public window onto the marts: it
has no API key check, so the mounting rule is the only thing standing between a
production deploy and an open data browser.

The second is that a failing stage degrades honestly -- reports the error, and lets the
remaining stages still run. That behaviour had a real bug: without a rollback, one bad
query in stage one made every later stage fail with "transaction is aborted", so a single
error arrived wearing four fake ones as a disguise.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import ProgrammingError

from app.core.settings import Settings
from app.showcase import pipeline, routes


# --------------------------------------------------------------------------- #
# it must not be public by accident
# --------------------------------------------------------------------------- #
def test_enabled_in_dev_by_default():
    assert routes.is_enabled(Settings(env="dev"))


def test_disabled_in_prod_by_default():
    """The showcase reads real data with no auth. Prod must opt in, never inherit it."""
    assert not routes.is_enabled(Settings(env="prod"))


def test_prod_can_opt_in_deliberately():
    assert routes.is_enabled(Settings(env="prod", showcase_enabled=True))


def test_dev_can_opt_out():
    assert not routes.is_enabled(Settings(env="dev", showcase_enabled=False))


def test_mount_is_skipped_when_disabled():
    app = MagicMock()
    with patch.object(routes, "is_enabled", return_value=False):
        assert routes.mount(app) is False
    app.include_router.assert_not_called()
    app.mount.assert_not_called()


# --------------------------------------------------------------------------- #
# stage wiring
# --------------------------------------------------------------------------- #
def test_every_stage_is_complete_and_unique():
    ids = [s["id"] for s in pipeline.STAGES]
    assert len(ids) == len(set(ids))
    for stage in pipeline.STAGES:
        assert stage["title"] and stage["subtitle"]
        assert callable(stage["fn"])


def test_console_rail_lists_exactly_the_real_stages():
    """The rail is hand-written HTML; a stage added in Python must be added there too."""
    html = (routes.TEMPLATES / "console.html").read_text(encoding="utf-8")
    for stage in pipeline.STAGES:
        assert f'data-stage="{stage["id"]}"' in html
    assert html.count("stage-item") == len(pipeline.STAGES)


# --------------------------------------------------------------------------- #
# failure handling
# --------------------------------------------------------------------------- #
def _broken_session() -> MagicMock:
    session = MagicMock()
    session.execute.side_effect = ProgrammingError("select 1", {}, Exception("boom"))
    return session


def test_a_failing_stage_does_not_end_the_run():
    session = _broken_session()
    scope = MagicMock()
    scope.__enter__.return_value = session

    with patch.object(pipeline, "session_scope", return_value=scope):
        events = list(pipeline.run_pipeline())

    # Every stage still got its turn, and the run still finished.
    assert sum(1 for e in events if e["t"] == "stage_done") == len(pipeline.STAGES)
    assert events[-1]["t"] == "done"
    assert any(e.get("cls") == "err" for e in events if e["t"] == "line")


def test_a_failing_stage_rolls_back_so_later_stages_still_work():
    """Regression: without this, one bad query aborted the transaction for the whole run."""
    session = _broken_session()
    scope = MagicMock()
    scope.__enter__.return_value = session

    with patch.object(pipeline, "session_scope", return_value=scope):
        list(pipeline.run_pipeline())

    assert session.rollback.call_count == len(pipeline.STAGES)


def test_an_unreachable_database_reports_rather_than_raising():
    with patch.object(pipeline, "session_scope", side_effect=OSError("connection refused")):
        events = list(pipeline.run_pipeline())

    assert events[-1] == {"t": "done", "ms": events[-1]["ms"], "ok": False}
    assert any("connection refused" in e.get("text", "") for e in events)


def test_only_runs_the_requested_stage():
    session = MagicMock()
    session.execute.return_value.mappings.return_value = []
    session.execute.return_value.scalar.return_value = 0
    scope = MagicMock()
    scope.__enter__.return_value = session

    with patch.object(pipeline, "session_scope", return_value=scope):
        events = list(pipeline.run_pipeline(only="resolve"))

    assert [e["id"] for e in events if e["t"] == "stage"] == ["resolve"]


# --------------------------------------------------------------------------- #
# SSE framing
# --------------------------------------------------------------------------- #
def test_events_are_framed_as_sse():
    frames = list(routes._sse(iter([{"t": "line", "text": "hello"}])))
    assert frames == ['data: {"t": "line", "text": "hello"}\n\n']


def test_decimals_and_dates_survive_serialisation():
    """Prices are Decimal and dates are date; neither is JSON-serialisable on its own."""
    from datetime import date
    from decimal import Decimal

    frame = next(iter(routes._sse(iter([{"p": Decimal("0.99"), "d": date(2026, 9, 1)}]))))
    payload = json.loads(frame.removeprefix("data: "))
    # Rendered from the Decimal, so it does not arrive as 0.9899999999999999.
    assert payload == {"p": "0.99", "d": "2026-09-01"}


@pytest.mark.parametrize("event", [{"t": "line", "text": "a\nb"}, {"t": "line", "text": "c\n\nd"}])
def test_newlines_in_text_cannot_break_the_frame(event):
    """A raw newline in an SSE payload would terminate the event early."""
    frame = next(iter(routes._sse(iter([event]))))
    assert frame.count("\n\n") == 1
    assert frame.endswith("\n\n")


# --------------------------------------------------------------------------- #
# the narrate stage and the live-fetch controls
# --------------------------------------------------------------------------- #
def test_narrate_is_the_last_stage():
    """It reads what the earlier stages computed, so it cannot run before them."""
    assert pipeline.STAGES[-1]["id"] == "narrate"


def test_narrate_says_so_when_no_model_is_configured():
    """The stage must not imply an LLM ran when none is configured."""
    from app.core.settings import Settings

    with patch.object(
        pipeline, "get_settings", return_value=Settings(_env_file=None, llm_model=None)
    ):
        events = list(pipeline.stage_narrate(MagicMock()))

    assert any("no model configured" in e.get("text", "") for e in events)
    assert not any(e["t"] == "prose" for e in events)


def test_the_console_offers_the_fetch_and_chat_controls():
    html = (routes.TEMPLATES / "console.html").read_text(encoding="utf-8")
    for control in ('id="fetch"', 'id="data"', 'id="dock-form"', 'id="dock-input"'):
        assert control in html


def test_hidden_panels_are_actually_hidden():
    """Regression: `display: flex` beat the browser's default `[hidden]` rule, so the
    data sheet and the chat panel both rendered while still marked hidden."""
    css = (routes.STATIC / "showcase.css").read_text(encoding="utf-8")
    assert ".sheet[hidden]" in css
    assert ".dock-panel[hidden]" in css


def test_the_fetch_limit_is_small_enough_to_watch():
    """It runs from a button while someone waits; a backfill belongs in the Celery sweep."""
    assert pipeline.FETCH_LIMIT <= 100


def test_a_failed_fetch_still_closes_the_stream():
    with patch("app.ingestion.runner.ingest_source", side_effect=OSError("upstream refused")):
        events = list(pipeline.run_fetch(10))

    assert events[-1]["t"] == "done"
    assert events[-1]["ok"] is False
    assert any(e.get("cls") == "err" for e in events if e["t"] == "line")
