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
    except Exception:
        pytest.skip("postgres is not reachable")
    yield eng
    eng.dispose()


@pytest.fixture
def two_sessions(engine):
    factory = sessionmaker(bind=engine)
    a, b = factory(), factory()
    yield a, b
    a.rollback()
    b.rollback()
    a.close()
    b.close()


def test_second_cycle_blocked_by_lock(two_sessions):
    first, second = two_sessions

    assert _acquire_cycle_lock(first) is True
    assert _acquire_cycle_lock(second) is False


def test_lock_released_on_commit(two_sessions):
    first, second = two_sessions

    assert _acquire_cycle_lock(first) is True
    assert _acquire_cycle_lock(second) is False

    first.rollback()

    assert _acquire_cycle_lock(second) is True


def test_same_session_reacquires(two_sessions):
    first, _ = two_sessions
    assert _acquire_cycle_lock(first) is True
    assert _acquire_cycle_lock(first) is True


def test_lock_key_pinned():
    assert ALERT_CYCLE_LOCK_KEY == 0x_A1E7_C7C1


def test_locked_cycle_writes_nothing(engine):
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
        load.assert_not_called()
        deliver.assert_not_called()
        blocked.close()
    finally:
        holder.rollback()
        holder.close()


def test_dry_run_ignores_lock(engine):
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


def test_lock_scoped_to_transaction(engine):
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
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        _acquire_cycle_lock(session)
        session.rollback()
        assert _held_locks(session) == 0
    finally:
        session.close()
