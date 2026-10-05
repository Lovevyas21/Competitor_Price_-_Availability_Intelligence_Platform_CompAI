from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.domain import (
    NormalizedRecord,
    PriceObservation,
    ProductAttributes,
    ProductIdentity,
)
from app.models.validation import IngestionBatchFailed, validate_price_batch


def make_record(price="4.19", currency="EUR", observed_at=None, external_id="1"):
    return NormalizedRecord(
        identity=ProductIdentity(source="test", external_id=external_id),
        attributes=ProductAttributes(title="Thing"),
        price=PriceObservation(
            price=Decimal(price),
            currency=currency,
            observed_at=observed_at or datetime.now(UTC) - timedelta(days=1),
        ),
        retailer_name="Shop",
    )


def test_valid_batch_passes():
    frame = validate_price_batch([make_record(), make_record(external_id="2")], source="test")
    assert frame.height == 2


def test_empty_batch_fails_loudly():
    with pytest.raises(IngestionBatchFailed, match="empty"):
        validate_price_batch([], source="test")


def test_batch_without_prices_fails():
    record = NormalizedRecord(
        identity=ProductIdentity(source="test", external_id="1"),
        attributes=ProductAttributes(),
        price=None,
    )
    with pytest.raises(IngestionBatchFailed, match="usable price"):
        validate_price_batch([record], source="test")


def test_future_dated_observation_is_rejected():
    future = datetime.now(UTC) + timedelta(days=3)
    with pytest.raises(IngestionBatchFailed, match="future"):
        validate_price_batch([make_record(observed_at=future)], source="test")


def test_bad_currency_length_is_rejected():
    with pytest.raises(IngestionBatchFailed):
        validate_price_batch([make_record(currency="EUROS")], source="test")


def test_negative_price_rejected_at_model_level():
    with pytest.raises(ValueError, match="negative"):
        make_record(price="-1")


def test_implausible_price_rejected_at_model_level():
    with pytest.raises(ValueError, match="implausibly large"):
        make_record(price="99999999999")
