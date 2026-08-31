"""SQLAlchemy 2.0 engine / session factory."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
    # Fail fast when Postgres is unreachable (e.g. Docker Desktop stopped) rather than
    # blocking a worker for the OS-level TCP timeout. Managed databases get a longer
    # budget: Neon's free tier scales compute to zero after 5 minutes idle, so the first
    # connection after a pause pays a cold start.
    connect_args={
        "connect_timeout": (
            30 if _settings.is_managed_database else _settings.db_connect_timeout_seconds
        )
    },
    # Recycle before a managed provider's idle timeout silently closes a pooled socket.
    pool_recycle=280,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
