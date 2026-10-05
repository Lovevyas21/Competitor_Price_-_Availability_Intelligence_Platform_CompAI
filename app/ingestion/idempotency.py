import hashlib
from datetime import datetime

from app.models.domain import IDEMPOTENCY_BUCKET_SECONDS


def bucket_timestamp(ts: datetime, bucket_seconds: int = IDEMPOTENCY_BUCKET_SECONDS) -> int:
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
    parts = [
        source,
        external_id,
        kind,
        discriminator or "-",
        str(bucket_timestamp(observed_at, bucket_seconds)),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
