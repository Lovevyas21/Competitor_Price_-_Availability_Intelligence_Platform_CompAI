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

DEFAULT_WINDOW_DAYS = 90

DEFAULT_ORDER = "-created"


def _parse_observed_at(raw: dict[str, Any]) -> datetime | None:
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
        return self._get_json(
            "/api/v1/prices",
            params={"product_code": external_id, "size": PAGE_SIZE},
        )

    def iter_raw(self, raw: Any) -> Iterator[Any]:
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            yield from raw["items"]
        else:
            yield raw

    def top_external_ids(self, limit: int = 50) -> list[tuple[str, int, str | None]]:
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
            stock=None,
            retailer_name=retailer,
            raw=raw,
        )
