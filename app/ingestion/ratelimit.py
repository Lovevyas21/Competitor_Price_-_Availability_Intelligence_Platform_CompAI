import time
from dataclasses import dataclass
from datetime import UTC, datetime

import redis

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

_TOKEN_BUCKET_LUA = """
local key       = KEYS[1]
local rate      = tonumber(ARGV[1])
local capacity  = tonumber(ARGV[2])
local now       = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl       = tonumber(ARGV[5])

local state  = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts     = tonumber(state[2])

if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)
return { allowed, tostring(tokens) }
"""


class RateLimited(RuntimeError):
    def __init__(self, source: str, retry_after: float) -> None:
        super().__init__(f"{source}: rate limited, retry in {retry_after:.1f}s")
        self.source = source
        self.retry_after = retry_after


class QuotaExhausted(RuntimeError):
    def __init__(self, source: str, limit: int) -> None:
        super().__init__(f"{source}: daily quota of {limit} calls exhausted")
        self.source = source
        self.limit = limit


@dataclass(frozen=True)
class SourceLimits:
    requests_per_minute: float = 60.0
    burst: int = 10
    daily_quota: int | None = None


SOURCE_LIMITS: dict[str, SourceLimits] = {
    "fakestore": SourceLimits(requests_per_minute=120, burst=20),
    "openprices": SourceLimits(requests_per_minute=60, burst=10),
    "bestbuy": SourceLimits(requests_per_minute=300, burst=50, daily_quota=50_000),
    "ebay": SourceLimits(requests_per_minute=180, burst=30, daily_quota=5_000),
    "digikey": SourceLimits(requests_per_minute=60, burst=10, daily_quota=1_000),
}

DEFAULT_LIMITS = SourceLimits()


def limits_for(source: str) -> SourceLimits:
    return SOURCE_LIMITS.get(source, DEFAULT_LIMITS)


def register_limits(source: str, limits: SourceLimits) -> None:
    SOURCE_LIMITS[source] = limits


class RateLimiter:
    def __init__(self, client: redis.Redis | None = None) -> None:
        self._redis = client or redis.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        self._bucket = self._redis.register_script(_TOKEN_BUCKET_LUA)

    def acquire(self, source: str, tokens: int = 1) -> None:
        limits = limits_for(source)
        rate_per_second = limits.requests_per_minute / 60.0
        allowed, remaining = self._bucket(
            keys=[f"ratelimit:{source}"],
            args=[rate_per_second, limits.burst, time.time(), tokens, 3600],
        )
        if not int(allowed):
            deficit = tokens - float(remaining)
            retry_after = max(deficit / rate_per_second, 0.1) if rate_per_second else 60.0
            log.warning("ratelimit.blocked", source=source, retry_after=round(retry_after, 2))
            raise RateLimited(source, retry_after)

    def consume_daily(self, source: str, count: int = 1) -> int:
        limits = limits_for(source)
        key = f"quota:{source}:{datetime.now(UTC):%Y%m%d}"
        used = int(self._redis.incrby(key, count))
        if used == count:
            self._redis.expire(key, 172_800)
        if limits.daily_quota is not None and used > limits.daily_quota:
            log.error("quota.exhausted", source=source, used=used, limit=limits.daily_quota)
            raise QuotaExhausted(source, limits.daily_quota)
        return used

    def quota_used(self, source: str) -> int:
        key = f"quota:{source}:{datetime.now(UTC):%Y%m%d}"
        return int(self._redis.get(key) or 0)

    def reset(self, source: str) -> None:
        self._redis.delete(f"ratelimit:{source}", f"quota:{source}:{datetime.now(UTC):%Y%m%d}")


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
