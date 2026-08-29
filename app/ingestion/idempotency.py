"""Idempotency keys.

Key = sha256(source | external_id | kind | time-bucket). The time bucket collapses
repeated fetches inside one window into a single logical observation, so a retried
Celery task or a replayed bronze payload cannot double-write history.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.models.domain import IDEMPOTENCY_BUCKET_SECONDS


def bucket_timestamp(ts: datetime, bucket_seconds: int = IDEMPOTENCY_BUCKET_SECONDS) -> int:
    """Floor a timestamp to the start of its bucket, as a unix epoch int."""
    epoch = int(ts.timestamp())
    return epoch - (epoch % bucket_seconds)


def idempotency_key(
    source: str,
    external_id: str,
    observed_at: datetime,
    kind: str = "price",
    discriminator: str | None = None,
    bucket_seconds: int = IDEMPOTENCY_BUCKET_SECONDS,
) -> str:
    """Build the dedupe key for one observation.

    `discriminator` separates observations that share a product and timestamp but are
    genuinely distinct -- most importantly the retailer. Without it, two stores'
    same-day prices for one barcode would collide and one would be silently dropped.
    """
    parts = [
        source,
        external_id,
        kind,
        discriminator or "-",
        str(bucket_timestamp(observed_at, bucket_seconds)),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
