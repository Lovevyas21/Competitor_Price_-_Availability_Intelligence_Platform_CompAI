"""FastAPI serving layer.

Endpoints read the dbt marts rather than the raw event tables. That keeps business logic
(what counts as an undercut, how volatility is measured) in one tested place instead of
being re-implemented in SQL scattered through handlers.

Run with: `make api`  ->  http://localhost:8000/docs
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.core.logging import configure_logging
from app.core.settings import get_settings

settings = get_settings()
configure_logging(settings.log_level, pretty=settings.env == "dev")

app = FastAPI(
    title=settings.api_title,
    version="1.0.0",
    description=(
        "Competitor price and availability intelligence. All endpoints except /health "
        "require an X-API-Key header when an API key is configured."
    ),
)

router = APIRouter(dependencies=[Depends(require_api_key)])


# --------------------------------------------------------------------------- #
# response models
# --------------------------------------------------------------------------- #
class Product(BaseModel):
    product_id: int
    external_id: str
    upc: str | None = None
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    tier: int
    source_name: str


class PricePoint(BaseModel):
    observed_date: date
    close_price: Decimal
    currency: str
    retailer_name: str | None = None
    change_pct: Decimal | None = None


class Forecast(BaseModel):
    product_id: int
    model: str
    horizon_days: int
    forecast_for: date
    yhat: Decimal | None = None
    yhat_lower: Decimal | None = None
    yhat_upper: Decimal | None = None
    trained_at: str


class Alert(BaseModel):
    alert_id: int
    product_id: int | None = None
    type: str
    message: str
    severity: str | None = None
    created_at: str
    sent_at: str | None = None


class UndercutRow(BaseModel):
    product_id: int
    product_name: str | None = None
    retailer_name: str | None = None
    currency: str
    our_price: Decimal
    competitor_price: Decimal
    gap_pct: Decimal
    severity: str
    confidence: str
    days_stale: int


class MatchReviewRow(BaseModel):
    match_id: int
    product_id_a: int
    product_id_b: int
    confidence: Decimal | None = None
    method: str | None = None
    status: str


class Health(BaseModel):
    status: str
    database: str
    auth_enabled: bool = Field(
        description="False means the API is unauthenticated -- surfaced so it cannot go unnoticed."
    )


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
@app.get("/health", response_model=Health, tags=["ops"])
def health(db: Session = Depends(get_db)) -> Health:
    try:
        db.execute(text("select 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - health must report, not raise
        database = "unavailable"
    return Health(
        status="ok" if database == "ok" else "degraded",
        database=database,
        auth_enabled=bool(settings.api_key),
    )


@router.get("/products", response_model=list[Product], tags=["catalogue"])
def list_products(
    db: Session = Depends(get_db),
    category: str | None = None,
    tier: int | None = Query(default=None, ge=1, le=3),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Product]:
    rows = db.execute(
        text("""
            select p.product_id, p.external_id, p.upc, pv.title,
                   coalesce(pv.brand, p.brand) as brand,
                   coalesce(pv.category, p.category) as category,
                   p.tier, s.name as source_name
            from products p
            join sources s on s.source_id = p.source_id
            left join product_versions pv
                   on pv.product_id = p.product_id and pv.is_current
            where (cast(:category as text) is null
                     or coalesce(pv.category, p.category) = cast(:category as text))
              and (cast(:tier as int) is null or p.tier = cast(:tier as int))
            order by p.product_id
            limit :limit offset :offset
        """),
        {"category": category, "tier": tier, "limit": limit, "offset": offset},
    ).mappings().all()
    return [Product(**r) for r in rows]


@router.get("/prices/{product_id}", response_model=list[PricePoint], tags=["prices"])
def price_history(
    product_id: int,
    db: Session = Depends(get_db),
    days: int = Query(default=90, ge=1, le=730),
) -> list[PricePoint]:
    rows = db.execute(
        text("""
            select observed_date, close_price, currency, retailer_name, change_pct
            from analytics_marts.mart_price_trend
            where product_id = :pid
              and observed_date >= current_date - cast(:days as int)
            order by observed_date desc
        """),
        {"pid": product_id, "days": days},
    ).mappings().all()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no price history for product {product_id} in the last {days} days",
        )
    return [PricePoint(**r) for r in rows]


@router.get("/forecasts/{product_id}", response_model=list[Forecast], tags=["forecasts"])
def forecasts(product_id: int, db: Session = Depends(get_db)) -> list[Forecast]:
    """Latest forecast run for a product. Older runs are kept but not returned."""
    rows = db.execute(
        text("""
            select product_id, model, horizon_days, forecast_for,
                   yhat, yhat_lower, yhat_upper, trained_at::text as trained_at
            from forecasts
            where product_id = :pid
              and trained_at = (select max(trained_at) from forecasts where product_id = :pid)
            order by forecast_for
        """),
        {"pid": product_id},
    ).mappings().all()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no forecast for product {product_id}; it may have too little history "
                "or its latest observation may be too stale to forecast"
            ),
        )
    return [Forecast(**r) for r in rows]


@router.get("/undercuts", response_model=list[UndercutRow], tags=["alerts"])
def undercuts(
    db: Session = Depends(get_db),
    severity: str | None = Query(default=None, pattern="^(medium|high|critical)$"),
    max_days_stale: int = Query(default=365, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[UndercutRow]:
    rows = db.execute(
        text("""
            select product_id, product_name, retailer_name, currency,
                   our_price, competitor_price, gap_pct, severity, confidence, days_stale
            from analytics_marts.mart_undercut_alerts
            where (cast(:severity as text) is null or severity = cast(:severity as text))
              and days_stale <= cast(:max_days_stale as int)
            order by gap_pct
            limit :limit
        """),
        {"severity": severity, "max_days_stale": max_days_stale, "limit": limit},
    ).mappings().all()
    return [UndercutRow(**r) for r in rows]


@router.get("/alerts", response_model=list[Alert], tags=["alerts"])
def alerts(
    db: Session = Depends(get_db),
    delivered: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Alert]:
    rows = db.execute(
        text("""
            select alert_id, product_id, type,
                   split_part(message, E'\\n#', 1) as message,
                   severity,
                   created_at::text as created_at,
                   sent_at::text as sent_at
            from alerts
            where (cast(:delivered as boolean) is null
                   or (cast(:delivered as boolean) and sent_at is not null)
                   or (not cast(:delivered as boolean) and sent_at is null))
            order by created_at desc
            limit :limit
        """),
        {"delivered": delivered, "limit": limit},
    ).mappings().all()
    return [Alert(**r) for r in rows]


@router.get("/matches/review", response_model=list[MatchReviewRow], tags=["matching"])
def matches_for_review(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[MatchReviewRow]:
    """Candidate product matches awaiting human review.

    Empty until phase 5 populates `product_matches` with embedding-based candidates.
    """
    rows = db.execute(
        text("""
            select match_id, product_id_a, product_id_b, confidence, method, status
            from product_matches
            where status = 'pending'
            order by confidence desc nulls last
            limit :limit
        """),
        {"limit": limit},
    ).mappings().all()
    return [MatchReviewRow(**r) for r in rows]


app.include_router(router)
