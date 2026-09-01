"""Open Prices client (the Open Food Facts price project) -- keyless, real price data.

Why this rather than the plain Open Food Facts product API: OFF carries product
attributes but no prices. Open Prices carries crowd-sourced observed prices, each with
a real observation date and an OSM store location -- so one product code genuinely
appears at several retailers over time. That is exactly the competitor-price shape this
platform exists to model, and it needs no API key.

Known payload quirks, handled below:
  * `date` and `currency` are nullable (they surface as null under some orderings).
  * price-level `product_name` is often null while the nested `product` object has it.
  * `price_is_discounted` rows carry the pre-discount price in `price_without_discount`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.clients.base import SourceClient
from app.core.logging import get_logger
from app.models.domain import (
    NormalizedRecord,
    PriceObservation,
    ProductAttributes,
    ProductIdentity,
)

log = get_logger(__name__)

PAGE_SIZE = 100

#: Default window for broad discovery.
#:
#: Without a date filter the API returns the oldest contributions first, which is how the
#: warehouse ended up full of observations from 2010-2020: real data, but far past the
#: 30-day staleness gate, so nothing was forecastable and every undercut read as stale.
#: Pulling a recent window is what makes the marts represent *now*.
DEFAULT_WINDOW_DAYS = 90

#: See discover() -- default ordering returns a single store/day and is useless here.
DEFAULT_ORDER = "-created"


def _parse_observed_at(raw: dict[str, Any]) -> datetime | None:
    """Prefer the in-store observation date; fall back to record creation time."""
    raw_date = raw.get("date")
    if raw_date:
        try:
            parsed = date.fromisoformat(str(raw_date)[:10])
            return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)
        except ValueError:
            log.warning("openprices.bad_date", value=raw_date, price_id=raw.get("id"))

    created = raw.get("created")
    if created:
        try:
            return datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        except ValueError:
            log.warning("openprices.bad_created", value=created, price_id=raw.get("id"))
    return None


class OpenPricesClient(SourceClient):
    name = "openprices"
    base_url = "https://prices.openfoodfacts.org"
    auth_type = "none"
    default_retailer = "Unknown store"
    country = None

    def fetch_raw(self, external_id: str) -> Any:
        """Fetch the recorded price history for one product barcode.

        Unlike `discover`, which is broad and shallow (many barcodes, one price each),
        this is narrow and deep: a well-tracked barcode returns ~100 dated observations
        across several stores. That depth is what per-SKU forecasting needs.
        """
        return self._get_json(
            "/api/v1/prices",
            params={"product_code": external_id, "size": PAGE_SIZE},
        )

    def iter_raw(self, raw: Any) -> Iterator[Any]:
        """A per-barcode fetch returns a page of price rows; yield them individually."""
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            yield from raw["items"]
        else:
            yield raw

    def top_external_ids(self, limit: int = 50) -> list[tuple[str, int, str | None]]:
        """Barcodes with the most recorded prices -- the best forecasting candidates."""
        payload = self._get_json(
            "/api/v1/products",
            params={"size": min(limit, PAGE_SIZE), "order_by": "-price_count"},
        )
        out: list[tuple[str, int, str | None]] = []
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            code = item.get("code")
            if code:
                out.append((str(code), int(item.get("price_count") or 0), item.get("product_name")))
        return out

    def discover(
        self, limit: int | None = None, order_by: str = DEFAULT_ORDER
    ) -> Iterator[tuple[str, Any]]:
        """Page through recent price observations.

        Each yielded item is one price row, so the same barcode can legitimately be
        yielded several times -- once per store/date. That is the point.

        Ordering matters more than it looks. The API's default order returns the
        earliest bulk import: 100 rows from a single store on a single day, which
        exercises nothing. `-created` returns recently contributed prices spread across
        many stores and dates (measured: 22 locations / 11 dates vs 1 / 1), which is the
        multi-retailer shape this platform needs. `-date` is avoided because it sorts
        NULLs first and yields rows with no date or currency.
        """
        wanted = limit or PAGE_SIZE
        emitted = 0
        page = 1
        while emitted < wanted:
            payload = self._get_json(
                "/api/v1/prices",
                params={
                    "size": min(PAGE_SIZE, wanted - emitted),
                    "page": page,
                    "order_by": order_by,
                },
            )
            items = payload.get("items") if isinstance(payload, dict) else None
            if not items:
                return
            for row in items:
                code = row.get("product_code")
                if not code:
                    continue
                yield str(code), row
                emitted += 1
                if emitted >= wanted:
                    return
            if page >= payload.get("pages", page):
                return
            page += 1

    def normalize(self, raw: Any) -> NormalizedRecord | None:
        if not isinstance(raw, dict):
            return None

        code = raw.get("product_code")
        if not code:
            return None

        # Currency is nullable upstream. Rather than guess a currency and silently
        # mislabel money, drop the observation and record why.
        currency = raw.get("currency")
        if not currency:
            log.warning("openprices.skip.no_currency", price_id=raw.get("id"), code=code)
            return None

        if raw.get("price") is None:
            log.warning("openprices.skip.no_price", price_id=raw.get("id"), code=code)
            return None
        try:
            price = Decimal(str(raw["price"]))
        except (InvalidOperation, ValueError):
            log.warning("openprices.skip.bad_price", value=raw.get("price"), code=code)
            return None

        observed_at = _parse_observed_at(raw)
        if observed_at is None:
            log.warning("openprices.skip.no_timestamp", price_id=raw.get("id"), code=code)
            return None

        product = raw.get("product") or {}
        location = raw.get("location") or {}

        # Precedence matters: the row-level `product_name` is contributor-entered free
        # text and varies per submission (one barcode showed 25 spellings), which would
        # churn a new SCD2 version per observation. The nested `product.product_name`
        # is Open Food Facts' canonical name and was stable across all of them.
        title = product.get("product_name") or raw.get("product_name")
        brands = product.get("brands")
        categories = product.get("categories_tags") or []
        category = raw.get("category_tag") or (categories[0] if categories else None)

        retailer = location.get("osm_brand") or location.get("osm_name") or self.default_retailer

        return NormalizedRecord(
            identity=ProductIdentity(
                source=self.name,
                external_id=str(code),
                upc=str(code),
                brand=brands,
                category=category,
                tier=2,
            ),
            attributes=ProductAttributes(
                title=title,
                brand=brands,
                category=category,
                attributes={
                    "quantity": product.get("quantity"),
                    "categories_tags": categories,
                    "labels_tags": product.get("labels_tags"),
                    "nutriscore_grade": product.get("nutriscore_grade"),
                    "price_is_discounted": raw.get("price_is_discounted"),
                    "price_without_discount": raw.get("price_without_discount"),
                    "location_osm_id": raw.get("location_osm_id"),
                    "location_country": location.get("osm_address_country_code"),
                },
            ),
            price=PriceObservation(
                price=price,
                currency=str(currency).upper(),
                observed_at=observed_at,
            ),
            # Open Prices records what a product cost, not whether it was in stock.
            stock=None,
            retailer_name=retailer,
            raw=raw,
        )
