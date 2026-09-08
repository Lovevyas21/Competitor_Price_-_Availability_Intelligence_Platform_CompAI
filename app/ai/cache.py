"""Narration cache, keyed by the facts a brief was written from.

The weekly brief gets regenerated far more often than the facts change: someone reloads
the page, a task retries, a demo runs twice. On a free-tier key each of those is a real
request against a small daily allowance, spent to produce text identical to the text
already produced.

Keying on a hash of the facts payload rather than on time is what makes this safe. The
brief is a function of the facts, so identical facts justify identical prose, and the
moment a single price moves the key changes and the model is asked again. There is no
window in which a stale brief can be served for fresh data.

Redis is already a dependency for the rate limiter and Celery, so this adds no
infrastructure. A missing or unreachable Redis is not an error: the cache degrades to
always-miss, which costs a request but never a wrong answer.
"""

from __future__ import annotations

import hashlib
import json

from app.ai.facts import WeeklyFacts
from app.core.logging import get_logger
from app.core.settings import Settings, get_settings

log = get_logger(__name__)

KEY_PREFIX = "brief:narration:"


def facts_fingerprint(facts: WeeklyFacts, model: str) -> str:
    """Identity of a brief: the facts it states, and the model that would write it.

    The model is part of the key because changing it is meant to change the prose. Were
    it excluded, switching models would keep serving the previous model's output until
    the underlying prices happened to move.

    `sort_keys` matters -- Python preserves insertion order, so two payloads holding the
    same facts could otherwise serialise differently and miss each other.
    """
    payload = json.dumps(facts.as_dict(), sort_keys=True, default=str)
    return hashlib.sha256(f"{model}|{payload}".encode()).hexdigest()[:32]


def _client(settings: Settings):
    import redis  # noqa: PLC0415

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get(fingerprint: str, settings: Settings | None = None) -> str | None:
    """Previously narrated brief for these facts, if one is still held."""
    s = settings or get_settings()
    if s.llm_cache_ttl_seconds <= 0:
        return None
    try:
        hit = _client(s).get(KEY_PREFIX + fingerprint)
    except Exception as exc:  # noqa: BLE001 - a cache must never break the caller
        log.warning("brief.cache_unavailable", error=str(exc)[:200])
        return None

    if hit:
        log.info("brief.cache_hit", fingerprint=fingerprint)
    return hit


def put(fingerprint: str, body: str, settings: Settings | None = None) -> None:
    """Remember a narration that passed the guard.

    Only guard-passing output reaches here. Caching a rejected brief would mean paying
    once for a bad answer and then serving it for a day.
    """
    s = settings or get_settings()
    if s.llm_cache_ttl_seconds <= 0:
        return
    try:
        _client(s).setex(KEY_PREFIX + fingerprint, s.llm_cache_ttl_seconds, body)
    except Exception as exc:  # noqa: BLE001
        log.warning("brief.cache_write_failed", error=str(exc)[:200])
