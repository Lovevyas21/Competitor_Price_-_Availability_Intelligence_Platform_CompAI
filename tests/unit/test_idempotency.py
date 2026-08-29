from datetime import UTC, datetime

from app.ingestion.idempotency import bucket_timestamp, idempotency_key

BASE = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def test_same_bucket_yields_same_key():
    """Two fetches seconds apart are one logical observation."""
    a = idempotency_key("openprices", "123", BASE)
    b = idempotency_key("openprices", "123", BASE.replace(second=45))
    assert a == b


def test_different_bucket_yields_different_key():
    later = BASE.replace(minute=5)
    assert idempotency_key("openprices", "123", BASE) != idempotency_key("openprices", "123", later)


def test_retailer_discriminator_prevents_collision():
    """Two stores pricing one barcode on one day must not collide."""
    a = idempotency_key("openprices", "123", BASE, discriminator="Carrefour")
    b = idempotency_key("openprices", "123", BASE, discriminator="Lidl")
    assert a != b


def test_kind_separates_price_and_stock():
    assert idempotency_key("s", "1", BASE, kind="price") != idempotency_key(
        "s", "1", BASE, kind="stock"
    )


def test_source_separates_identical_external_ids():
    assert idempotency_key("a", "1", BASE) != idempotency_key("b", "1", BASE)


def test_bucket_floors_to_window_start():
    assert bucket_timestamp(BASE.replace(second=59)) == bucket_timestamp(BASE)
