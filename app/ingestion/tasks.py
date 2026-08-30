"""Celery tasks.

Failure policy, in layers:

  * **Transport errors** (`httpx` timeouts, 5xx) auto-retry with exponential backoff and
    jitter. Jitter matters: without it, a fan-out of 500 SKUs that all fail on an
    upstream blip would retry in lockstep and hammer the API again.
  * **Rate limiting** retries after the limiter's own `retry_after`, so the task waits
    exactly as long as the bucket needs rather than a fixed guess.
  * **Quota exhaustion** does *not* retry -- the quota resets tomorrow, so burning
    retries today is pointless. The task dead-letters immediately.
  * **Anything still failing after max retries** is written to the dead-letter store
    with its context, so it can be inspected and replayed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import text

from app.celery_app import app
from app.clients.registry import CLIENTS, get_client
from app.core.db import session_scope
from app.core.logging import get_logger
from app.ingestion.bronze import get_bronze_store, get_deadletter_store
from app.ingestion.cdc import CDCStats, apply_record, get_or_create_source
from app.ingestion.idempotency import idempotency_key
from app.ingestion.ratelimit import QuotaExhausted, RateLimited, get_rate_limiter
from app.ingestion.runner import ingest_seeds, ingest_source
from app.models.domain import NormalizedRecord
from app.models.validation import IngestionBatchFailed, validate_price_batch

log = get_logger(__name__)

RETRYABLE_TRANSPORT = (httpx.TransportError, httpx.HTTPStatusError)


def dead_letter(reason: str, context: dict[str, Any], payload: Any = None) -> str:
    """Persist a permanently failed unit of work for later inspection/replay."""
    store = get_deadletter_store()
    now = datetime.now(UTC)
    source = context.get("source", "unknown")
    key = idempotency_key(
        source, str(context.get("external_id", "batch")), now, kind=f"dlq:{reason}"
    )
    location = store.put(
        source,
        now,
        key,
        {"reason": reason, "context": context, "failed_at": now.isoformat(), "payload": payload},
    )
    log.error("task.dead_lettered", reason=reason, location=location, **context)
    return location


# --------------------------------------------------------------------------- #
# per-SKU fetch -- the fan-out unit
# --------------------------------------------------------------------------- #
@shared_task(
    bind=True,
    name="app.ingestion.tasks.fetch_sku",
    autoretry_for=RETRYABLE_TRANSPORT,
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
    # Coarse per-worker throttle. The Redis token bucket below is the real enforcement --
    # this one is per-worker, so it does not hold when workers scale out. It is kept as a
    # cheap first line of defence against a runaway fan-out on a single worker.
    rate_limit="120/m",
)
def fetch_sku(self, source: str, external_id: str) -> dict:
    """Fetch and apply one SKU's observations.

    Rate limiting happens before the HTTP call, and the daily quota is only consumed
    once the call is actually going out -- so a task that parks on the rate limiter does
    not spend quota it never used.
    """
    limiter = get_rate_limiter()
    try:
        limiter.acquire(source)
    except RateLimited as exc:
        raise self.retry(exc=exc, countdown=exc.retry_after) from exc

    try:
        limiter.consume_daily(source)
    except QuotaExhausted as exc:
        # Retrying inside the same day cannot succeed; fail fast and record it.
        dead_letter("quota_exhausted", {"source": source, "external_id": external_id})
        raise exc

    client = get_client(source)
    try:
        raw = client.fetch_raw(external_id)
        get_bronze_store().put(
            source,
            datetime.now(UTC),
            idempotency_key(source, external_id, datetime.now(UTC), kind="raw"),
            raw,
        )

        records: list[NormalizedRecord] = []
        for row in client.iter_raw(raw):
            record = client.normalize(row)
            if record is not None:
                records.append(record)

        if not records:
            log.warning("fetch_sku.no_records", source=source, external_id=external_id)
            return {"source": source, "external_id": external_id, "applied": 0}

        validate_price_batch(records, source=source)

        stats = CDCStats()
        with session_scope() as session:
            source_id = get_or_create_source(
                session, client.name, client.base_url, client.auth_type
            )
            for record in sorted(records, key=lambda r: r.observed_at):
                apply_record(session, source_id, record, stats)

        log.info(
            "fetch_sku.done",
            source=source,
            external_id=external_id,
            inserted=stats.price_events_inserted,
        )
        return {
            "source": source,
            "external_id": external_id,
            "inserted": stats.price_events_inserted,
            "skipped_unchanged": stats.price_events_skipped_unchanged,
        }

    except IngestionBatchFailed as exc:
        dead_letter(
            "validation_failed",
            {"source": source, "external_id": external_id, "error": str(exc)},
        )
        raise
    except RETRYABLE_TRANSPORT as exc:
        # Let autoretry handle it, but dead-letter once retries are exhausted.
        if self.request.retries >= self.max_retries:
            dead_letter(
                "transport_retries_exhausted",
                {"source": source, "external_id": external_id, "error": str(exc)},
            )
        raise
    except MaxRetriesExceededError as exc:
        dead_letter(
            "max_retries", {"source": source, "external_id": external_id, "error": str(exc)}
        )
        raise
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# scheduling / fan-out
# --------------------------------------------------------------------------- #
@shared_task(name="app.ingestion.tasks.enqueue_tier", acks_late=True)
def enqueue_tier(tier: int) -> dict:
    """Fan out per-SKU fetches for every active seed at this tier."""
    with session_scope() as session:
        rows = session.execute(
            text("""
                select source_name, external_id
                from seed_products
                where active and tier = :tier
                order by source_name, seed_id
            """),
            {"tier": tier},
        ).all()

    known = set(CLIENTS)
    enqueued = 0
    skipped_unknown = 0
    for source_name, external_id in rows:
        if source_name not in known:
            skipped_unknown += 1
            continue
        fetch_sku.delay(source_name, external_id)
        enqueued += 1

    log.info("enqueue_tier.done", tier=tier, enqueued=enqueued, unknown=skipped_unknown)
    return {"tier": tier, "enqueued": enqueued, "skipped_unknown_source": skipped_unknown}


@shared_task(name="app.ingestion.tasks.ingest_source_task", acks_late=True)
def ingest_source_task(source: str, limit: int = 100) -> dict:
    """Broad discovery sweep for one source."""
    result = ingest_source(source, limit=limit)
    if result.status != "success":
        dead_letter("discovery_failed", {"source": source, "error": result.error})
    return result.summary()


@shared_task(name="app.ingestion.tasks.ingest_seeds_task", acks_late=True)
def ingest_seeds_task(source: str, max_products: int = 25) -> dict:
    """Deep history fetch for seeded SKUs, in one task rather than fanned out."""
    result = ingest_seeds(source, max_products=max_products)
    if result.status != "success":
        dead_letter("seed_ingest_failed", {"source": source, "error": result.error})
    return result.summary()


# --------------------------------------------------------------------------- #
# maintenance
# --------------------------------------------------------------------------- #
@shared_task(name="app.ingestion.tasks.ensure_future_partitions", acks_late=True)
def ensure_future_partitions(months_ahead: int = 3) -> dict:
    """Pre-create upcoming monthly partitions.

    Runs on the 25th so next month's partition exists days before the boundary; a
    missing partition makes every write for that month fail.
    """
    created = []
    today = datetime.now(UTC).date().replace(day=1)
    with session_scope() as session:
        for offset in range(months_ahead + 1):
            month = today
            for _ in range(offset):
                month = (month + timedelta(days=32)).replace(day=1)
            for parent in ("price_events", "stock_events"):
                session.execute(
                    text("select ensure_month_partition(:parent, :month)"),
                    {"parent": parent, "month": month},
                )
                created.append(f"{parent}_{month:%Y%m}")

    log.info("partitions.ensured", count=len(created))
    return {"ensured": created}


@shared_task(name="app.ingestion.tasks.replay_from_bronze", acks_late=True)
def replay_from_bronze(source: str, day: str) -> dict:
    """Re-parse and re-apply stored raw payloads for one source/day.

    This is why raw lands in bronze before parsing: when a normalizer bug is fixed, the
    corrected logic is replayed over the original payloads with no upstream traffic and
    no quota spend. Idempotency keys make the replay safe to run repeatedly -- unchanged
    observations collapse instead of duplicating history.
    """
    try:
        target = datetime.fromisoformat(day).replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"day must be ISO format (YYYY-MM-DD), got {day!r}") from exc

    client = get_client(source)
    store = get_bronze_store()
    records: list[NormalizedRecord] = []
    payloads = 0

    try:
        for payload in store.iter_payloads(source, target):
            payloads += 1
            for row in client.iter_raw(payload):
                record = client.normalize(row)
                if record is not None:
                    records.append(record)
    finally:
        client.close()

    if not records:
        log.warning("replay.no_records", source=source, day=day, payloads=payloads)
        return {"source": source, "day": day, "payloads": payloads, "applied": 0}

    validate_price_batch(records, source=source)

    stats = CDCStats()
    with session_scope() as session:
        source_id = get_or_create_source(session, client.name, client.base_url, client.auth_type)
        for record in sorted(records, key=lambda r: r.observed_at):
            apply_record(session, source_id, record, stats)

    log.info("replay.done", source=source, day=day, payloads=payloads, **stats.as_dict())
    return {
        "source": source,
        "day": day,
        "payloads": payloads,
        "records": len(records),
        "inserted": stats.price_events_inserted,
        "skipped_unchanged": stats.price_events_skipped_unchanged,
        "duplicate": stats.price_events_duplicate,
    }


@shared_task(name="app.ingestion.tasks.ping")
def ping() -> str:
    """Liveness probe used by tests and smoke checks."""
    return "pong"


# Keep a module-level reference so `celery -A app.celery_app` registers these.
__all__ = [
    "app",
    "enqueue_tier",
    "ensure_future_partitions",
    "fetch_sku",
    "ingest_seeds_task",
    "ingest_source_task",
    "ping",
    "replay_from_bronze",
]
