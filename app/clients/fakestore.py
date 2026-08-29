"""Fake Store API client -- keyless pseudo-e-commerce data.

Used for local dev, tests, and to exercise the full pipeline without burning a real
API quota. Payloads are static upstream, so this source proves the code path but will
not produce genuine price drift. See ADR-001.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
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


class FakeStoreClient(SourceClient):
    name = "fakestore"
    base_url = "https://fakestoreapi.com"
    auth_type = "none"
    default_retailer = "Fake Store"
    country = "US"

    def fetch_raw(self, external_id: str) -> Any:
        return self._get_json(f"/products/{external_id}")

    def discover(self, limit: int | None = None) -> Iterator[tuple[str, Any]]:
        params = {"limit": limit} if limit else {}
        payload = self._get_json("/products", params=params)
        if not isinstance(payload, list):
            log.warning("fakestore.discover.unexpected_payload", type=type(payload).__name__)
            return
        for item in payload:
            if isinstance(item, dict) and item.get("id") is not None:
                yield str(item["id"]), item

    def normalize(self, raw: Any) -> NormalizedRecord | None:
        if not isinstance(raw, dict) or raw.get("id") is None:
            return None
        if raw.get("price") is None:
            log.warning("fakestore.normalize.no_price", external_id=raw.get("id"))
            return None

        observed_at = datetime.now(UTC)
        category = raw.get("category")

        return NormalizedRecord(
            identity=ProductIdentity(
                source=self.name,
                external_id=str(raw["id"]),
                sku=f"FS-{raw['id']}",
                category=category,
                tier=2,
            ),
            attributes=ProductAttributes(
                title=raw.get("title"),
                category=category,
                attributes={
                    "description": raw.get("description"),
                    "image": raw.get("image"),
                    "rating": raw.get("rating"),
                },
            ),
            price=PriceObservation(
                price=Decimal(str(raw["price"])),
                currency="USD",
                observed_at=observed_at,
            ),
            # Fake Store exposes no availability field. Left None rather than invented;
            # stock_events populate once a source with real availability lands.
            stock=None,
            retailer_name=self.default_retailer,
            raw=raw,
        )
