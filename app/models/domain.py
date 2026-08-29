"""Normalized domain models.

Every source client, regardless of how weird its upstream payload is, must produce a
`NormalizedRecord`. This is the seam that lets Best Buy / eBay / Digi-Key drop in later
without touching the CDC or storage layers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bucket observations to the minute for idempotency purposes. Two fetches of the same
# SKU inside one minute are treated as the same observation.
IDEMPOTENCY_BUCKET_SECONDS = 60


class ProductIdentity(BaseModel):
    """Stable identity of a product within one source."""

    model_config = ConfigDict(frozen=True)

    source: str
    external_id: str
    sku: str | None = None
    upc: str | None = None
    mpn: str | None = None
    brand: str | None = None
    category: str | None = None
    tier: int = Field(default=3, ge=1, le=3)

    @field_validator("external_id")
    @classmethod
    def _external_id_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("external_id must not be blank")
        return v


class ProductAttributes(BaseModel):
    """Mutable descriptive attributes -- these are what SCD2 versions track."""

    title: str | None = None
    brand: str | None = None
    category: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    def scd2_fingerprint(self) -> tuple:
        """Values whose change opens a new product_versions row.

        `attributes` is deliberately excluded: source payloads carry noisy fields
        (view counts, image CDN URLs) that would churn versions without meaning.
        """
        return (self.title, self.brand, self.category)


class PriceObservation(BaseModel):
    price: Decimal
    currency: str = "USD"
    observed_at: datetime

    @field_validator("price")
    @classmethod
    def _price_sane(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("price must not be negative")
        if v > Decimal("10000000"):
            raise ValueError("price implausibly large")
        return v

    @field_validator("observed_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class StockObservation(BaseModel):
    in_stock: bool | None = None
    quantity: int | None = Field(default=None, ge=0)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class NormalizedRecord(BaseModel):
    """One product observed once, from one source."""

    identity: ProductIdentity
    attributes: ProductAttributes
    price: PriceObservation | None = None
    stock: StockObservation | None = None
    retailer_name: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def observed_at(self) -> datetime:
        for obs in (self.price, self.stock):
            if obs is not None:
                return obs.observed_at
        return datetime.now(UTC)
