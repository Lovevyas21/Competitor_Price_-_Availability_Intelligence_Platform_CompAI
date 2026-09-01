"""Rate limiter tests against a real Redis.

Real Redis rather than a fake: the whole point of this limiter is that the token bucket
is atomic across processes, and that property lives in the Lua script and Redis itself.
A fake would test the Python wrapper and skip what matters.
"""

from __future__ import annotations

import time
import uuid

import pytest
import redis

from app.core.settings import get_settings
from app.ingestion.ratelimit import (
    QuotaExhausted,
    RateLimited,
    RateLimiter,
    SourceLimits,
    limits_for,
)


@pytest.fixture(scope="module")
def redis_client():
    """Connect to the real Redis, retrying briefly before giving up.

    A single short-timeout ping skips spuriously when the machine is under memory
    pressure, and a skipped test looks the same as a passing one in a summary line --
    which is how a genuine regression goes unnoticed. Retry first, skip only if Redis
    is really absent.
    """
    client = redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            client.ping()
            return client
        except redis.exceptions.RedisError as exc:
            last_error = exc
            time.sleep(1 + attempt)
    pytest.skip(f"redis not reachable ({last_error}); run `docker compose up -d redis`")


@pytest.fixture
def limiter(redis_client):
    return RateLimiter(redis_client)


#: Refill rate for the test bucket, deliberately slow.
#:
#: At the obvious 60/min the bucket refills a token every second, so "spend the burst,
#: then assert the next call is refused" silently depends on four Redis round-trips
#: completing inside one second. Under CPU or memory pressure they do not, a token
#: refills, the call legitimately succeeds, and the test fails without anything being
#: wrong. At 6/min a token takes ten seconds, which no longer races the assertion.
TEST_RPM = 6.0
TEST_BURST = 3
SECONDS_PER_TOKEN = 60.0 / TEST_RPM  # 10s


@pytest.fixture
def source(monkeypatch):
    """A unique source name per test, so runs cannot interfere with each other."""
    name = f"test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setitem(
        __import__("app.ingestion.ratelimit", fromlist=["SOURCE_LIMITS"]).SOURCE_LIMITS,
        name,
        SourceLimits(requests_per_minute=TEST_RPM, burst=TEST_BURST, daily_quota=5),
    )
    return name


def test_burst_is_allowed_then_blocked(limiter, source):
    """Capacity equals burst; the next call must be refused, not silently allowed."""
    for _ in range(TEST_BURST):
        limiter.acquire(source)

    with pytest.raises(RateLimited) as exc:
        limiter.acquire(source)
    assert exc.value.retry_after > 0


def test_retry_after_is_a_usable_hint(limiter, source):
    for _ in range(TEST_BURST):
        limiter.acquire(source)
    with pytest.raises(RateLimited) as exc:
        limiter.acquire(source)
    # One token away, at SECONDS_PER_TOKEN each. Bounded generously rather than exactly:
    # the point is that the hint is usable, not that the clock is precise.
    assert 0 < exc.value.retry_after <= SECONDS_PER_TOKEN * 1.5


def test_limiter_state_is_shared_across_instances(redis_client, source):
    """Two workers must share one budget, not get one each."""
    a = RateLimiter(redis_client)
    b = RateLimiter(redis_client)
    for _ in range(TEST_BURST):
        a.acquire(source)
    with pytest.raises(RateLimited):
        b.acquire(source)


def test_daily_quota_counts_and_then_raises(limiter, source):
    for _ in range(5):
        limiter.consume_daily(source)
    assert limiter.quota_used(source) == 5
    with pytest.raises(QuotaExhausted):
        limiter.consume_daily(source)


def test_reset_clears_both_guards(limiter, source):
    for _ in range(TEST_BURST):
        limiter.acquire(source)
    limiter.consume_daily(source)
    limiter.reset(source)
    assert limiter.quota_used(source) == 0
    limiter.acquire(source)  # must not raise


def test_unknown_source_falls_back_to_defaults():
    assert limits_for("does-not-exist").requests_per_minute == 60.0


def test_ebay_limit_matches_documented_daily_cap():
    """eBay's documented app-level production default is 5,000 calls/day."""
    assert limits_for("ebay").daily_quota == 5_000
