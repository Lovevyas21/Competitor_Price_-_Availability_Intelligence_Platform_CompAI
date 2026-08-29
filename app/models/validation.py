"""Ingestion-time data quality gate.

Two layers of defence, deliberately:
  * pydantic validates each record's *shape* as it is normalized (per-record, fail-soft).
  * pandera validates the *batch* before it reaches Postgres (cross-record, fail-loud).

The batch check catches problems a per-record check cannot see -- an entire source
returning zero rows, or a price column that has gone all-null after an upstream change.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandera.polars as pa
import polars as pl
from pandera.errors import SchemaError, SchemaErrors

from app.core.logging import get_logger
from app.models.domain import NormalizedRecord

log = get_logger(__name__)

MAX_PLAUSIBLE_PRICE = 10_000_000.0


class IngestionBatchFailed(RuntimeError):
    """Raised when a parsed batch fails its data-quality contract."""


price_batch_schema = pa.DataFrameSchema(
    {
        "source": pa.Column(str, nullable=False),
        "external_id": pa.Column(str, nullable=False),
        "retailer_name": pa.Column(str, nullable=True),
        "price": pa.Column(
            float,
            checks=[
                pa.Check.ge(0, error="price must not be negative"),
                pa.Check.le(MAX_PLAUSIBLE_PRICE, error="price implausibly large"),
            ],
            nullable=False,
        ),
        "currency": pa.Column(
            str,
            checks=pa.Check.str_length(3, 3, error="currency must be a 3-letter code"),
            nullable=False,
        ),
        "observed_at": pa.Column(pl.Datetime, nullable=False),
    },
    strict=False,
)


def records_to_frame(records: list[NormalizedRecord]) -> pl.DataFrame:
    rows = [
        {
            "source": r.identity.source,
            "external_id": r.identity.external_id,
            "retailer_name": r.retailer_name,
            "price": float(r.price.price),
            "currency": r.price.currency,
            "observed_at": r.price.observed_at.astimezone(UTC).replace(tzinfo=None),
        }
        for r in records
        if r.price is not None
    ]
    return pl.DataFrame(rows, schema_overrides={"observed_at": pl.Datetime})


def validate_price_batch(records: list[NormalizedRecord], *, source: str) -> pl.DataFrame:
    """Validate a parsed batch. Raises IngestionBatchFailed on contract violation."""
    if not records:
        raise IngestionBatchFailed(f"{source}: parsed batch is empty")

    frame = records_to_frame(records)
    if frame.is_empty():
        raise IngestionBatchFailed(f"{source}: no records carried a usable price")

    try:
        validated = price_batch_schema.validate(frame, lazy=True)
    except (SchemaError, SchemaErrors) as exc:  # lazy=True raises the plural form
        raise IngestionBatchFailed(f"{source}: batch failed schema checks: {exc}") from exc

    future = validated.filter(
        pl.col("observed_at") > pl.lit(datetime.now(UTC).replace(tzinfo=None))
    )
    if future.height:
        raise IngestionBatchFailed(f"{source}: {future.height} observation(s) dated in the future")

    log.info("validation.batch_ok", source=source, rows=validated.height)
    return validated
