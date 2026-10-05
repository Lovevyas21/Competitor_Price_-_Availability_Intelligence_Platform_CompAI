from __future__ import annotations

import hashlib
import json

from app.ai.facts import WeeklyFacts
from app.core.logging import get_logger
from app.core.settings import Settings, get_settings

log = get_logger(__name__)

KEY_PREFIX = "brief:narration:"


def facts_fingerprint(facts: WeeklyFacts, model: str) -> str:
    payload = json.dumps(facts.as_dict(), sort_keys=True, default=str)
    return hashlib.sha256(f"{model}|{payload}".encode()).hexdigest()[:32]


def _client(settings: Settings):
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get(fingerprint: str, settings: Settings | None = None) -> str | None:
    s = settings or get_settings()
    if s.llm_cache_ttl_seconds <= 0:
        return None
    try:
        hit = _client(s).get(KEY_PREFIX + fingerprint)
    except Exception as exc:
        log.warning("brief.cache_unavailable", error=str(exc)[:200])
        return None

    if hit:
        log.info("brief.cache_hit", fingerprint=fingerprint)
    return hit


def put(fingerprint: str, body: str, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    if s.llm_cache_ttl_seconds <= 0:
        return
    try:
        _client(s).setex(KEY_PREFIX + fingerprint, s.llm_cache_ttl_seconds, body)
    except Exception as exc:
        log.warning("brief.cache_write_failed", error=str(exc)[:200])
