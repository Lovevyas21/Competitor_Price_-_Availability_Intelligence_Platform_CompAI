"""Alert-cycle mutual exclusion, against a real Postgres.

A real database rather than a mock, for the same reason the rate limiter uses a real
Redis: the property under test is that *two separate connections* exclude each other.
That lives in Postgres, not in the Python wrapper. Mocking `pg_try_advisory_xact_lock`
would assert that a function was called and prove nothing about whether it works.

The bug this guards against sends a human the same undercut twice. It cannot be
reproduced on one connection, which is why it survived every unit test.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.alerting import service
from app.alerting.service import ALERT_CYCLE_LOCK_KEY, _acquire_cycle_lock
from app.core.settings import get_settings


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("select 1"))
    except Exception:  # pragma: no cover - skipped when no database is running
        pytest.skip("postgres is not reachable")
    yield eng
    eng.dispose()


@pytest.fixture
def two_sessions(engine):
    """Two genuinely independent connections, as two schedulers would have."""
    factory = sessionmaker(bind=engine)
    a, b = factory(), factory()
    yield a, b
    a.rollback()
    b.rollback()
    a.close()
    b.close()


def test_the_second_cycle_is_refused_while_the_first_holds_the_lock(two_sessions):
    first, second = two_sessions

    assert _acquire_cycle_lock(first) is True
    # This is the assertion the whole fix exists for.
    assert _acquire_cycle_lock(second) is False


def test_the_lock_is_released_when_the_transaction_ends(two_sessions):
    """Transaction-scoped, so a crashed cycle cannot wedge the schedule permanently."""
    first, second = two_sessions

    assert _acquire_cycle_lock(first) is True
    assert _acquire_cycle_lock(second) is False

    first.rollback()  # as a failed cycle would

    assert _acquire_cycle_lock(second) is True


def test_the_same_session_may_reacquire(two_sessions):
    """Postgres advisory locks are re-entrant per session; a retry must not deadlock."""
    first, _ = two_sessions
    assert _acquire_cycle_lock(first) is True
    assert _acquire_cycle_lock(first) is True


def test_the_lock_key_is_pinned():
    """Changing it would mean two deployments no longer exclude each other."""
    assert ALERT_CYCLE_LOCK_KEY == 0x_A1E7_C7C1


def test_a_locked_out_cycle_writes_nothing_and_says_so(engine):
    """The refusal must be visible in the stats, not a silent no-op."""
    factory = sessionmaker(bind=engine)
    holder = factory()
    try:
        assert _acquire_cycle_lock(holder) is True

        blocked = factory()
        scope = MagicMock()
        scope.__enter__.return_value = blocked
        with (
            patch.object(service, "session_scope", return_value=scope),
            patch.object(service, "load_candidates") as load,
            patch.object(service, "deliver") as deliver,
        ):
            stats = service.run_alert_cycle()

        assert stats["skipped_locked"] is True
        assert stats["created"] == 0
        # It gave up before doing any work at all, not after.
        load.assert_not_called()
        deliver.assert_not_called()
        blocked.close()
    finally:
        holder.rollback()
        holder.close()


def test_a_dry_run_is_not_blocked_by_a_running_cycle(engine):
    """A preview writes nothing, so it needs no exclusion and must not wait for one."""
    factory = sessionmaker(bind=engine)
    holder = factory()
    try:
        assert _acquire_cycle_lock(holder) is True

        previewer = factory()
        scope = MagicMock()
        scope.__enter__.return_value = previewer
        with (
            patch.object(service, "session_scope", return_value=scope),
            patch.object(service, "load_candidates", return_value=[]),
            patch.object(service, "existing_fingerprints", return_value={}),
        ):
            stats = service.run_alert_cycle(dry_run=True)

        assert stats["skipped_locked"] is False
        previewer.close()
    finally:
        holder.rollback()
        holder.close()


def test_the_lock_does_not_leak_into_other_work(engine):
    """It must guard the alert cycle only, not serialise unrelated queries."""
    factory = sessionmaker(bind=engine)
    holder, other = factory(), factory()
    try:
        assert _acquire_cycle_lock(holder) is True
        assert other.execute(text("select count(*) from alerts")).scalar() is not None
    finally:
        for s in (holder, other):
            s.rollback()
            s.close()


def _held_locks(session: Session) -> int:
    return session.execute(
        text("select count(*) from pg_locks where locktype = 'advisory' and objid = :k"),
        {"k": ALERT_CYCLE_LOCK_KEY},
    ).scalar()


def test_no_advisory_lock_is_left_behind(engine):
    """A leaked session-scoped lock would block every later cycle until a restart."""
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        _acquire_cycle_lock(session)
        session.rollback()
        assert _held_locks(session) == 0
    finally:
        session.close()
