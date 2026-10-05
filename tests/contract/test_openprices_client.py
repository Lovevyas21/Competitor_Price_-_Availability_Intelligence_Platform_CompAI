from datetime import UTC

import pytest

from app.clients.openprices import OpenPricesClient


def price_row(**overrides):
    row = {
        "id": 1,
        "product_code": "3017620422003",
        "product_name": "nutella pot 750g",
        "price": 4.19,
        "currency": "EUR",
        "date": "2026-08-26",
        "created": "2026-08-26T10:00:00Z",
        "price_is_discounted": False,
        "location_osm_id": 42,
        "product": {"product_name": "Nutella", "brands": "Ferrero", "categories_tags": ["spreads"]},
        "location": {"osm_name": "Carrefour Lyon", "osm_address_country_code": "FR"},
    }
    row.update(overrides)
    return row


@pytest.fixture
def client():
    c = OpenPricesClient()
    yield c
    c.close()


def test_normalize_happy_path(client):
    rec = client.normalize(price_row())
    assert rec is not None
    assert rec.identity.external_id == "3017620422003"
    assert rec.identity.upc == "3017620422003"
    assert float(rec.price.price) == 4.19
    assert rec.price.currency == "EUR"
    assert rec.price.observed_at.astimezone(UTC).date().isoformat() == "2026-08-26"
    assert rec.retailer_name == "Carrefour Lyon"


def test_canonical_title_wins_over_contributor_text(client):
    rec = client.normalize(price_row())
    assert rec.attributes.title == "Nutella"


def test_falls_back_to_row_name_when_canonical_missing(client):
    rec = client.normalize(price_row(product={"product_name": None, "brands": None}))
    assert rec.attributes.title == "nutella pot 750g"


def test_null_currency_is_skipped_not_guessed(client):
    assert client.normalize(price_row(currency=None)) is None


def test_null_price_is_skipped(client):
    assert client.normalize(price_row(price=None)) is None


def test_missing_date_falls_back_to_created(client):
    rec = client.normalize(price_row(date=None))
    assert rec is not None
    assert rec.price.observed_at.year == 2026


def test_no_usable_timestamp_is_skipped(client):
    assert client.normalize(price_row(date=None, created=None)) is None


def test_malformed_date_falls_back_rather_than_raising(client):
    rec = client.normalize(price_row(date="not-a-date"))
    assert rec is not None
    assert rec.price.observed_at.year == 2026


def test_missing_product_code_is_skipped(client):
    assert client.normalize(price_row(product_code=None)) is None


def test_non_dict_payload_is_skipped(client):
    assert client.normalize(["unexpected"]) is None


def test_brand_prefers_osm_brand_over_name(client):
    rec = client.normalize(
        price_row(location={"osm_brand": "Lidl", "osm_name": "Lidl Rue Garibaldi"})
    )
    assert rec.retailer_name == "Lidl"


def test_iter_raw_splits_history_page(client):
    page = {"items": [price_row(id=1), price_row(id=2)]}
    assert len(list(client.iter_raw(page))) == 2


def test_iter_raw_passes_through_single_payload(client):
    assert list(client.iter_raw(price_row())) == [price_row()]
