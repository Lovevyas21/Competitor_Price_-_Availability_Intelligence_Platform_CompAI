"""API dependencies: database sessions and authentication."""

from __future__ import annotations

import secrets
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.settings import Settings, get_settings


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate the API key header.

    When no key is configured the API is open -- deliberate for local development, and
    surfaced in `/health` so an unauthenticated deployment cannot go unnoticed.

    The comparison is constant-time: a plain `==` leaks key material through timing.
    """
    if not settings.api_key:
        return

    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
