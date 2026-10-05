from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)

TOP_N = 5


def _d(value) -> float | None:
    if value is None:
        return None
    return round(float(Decimal(str(value))), 2)


@dataclass
class WeeklyFacts:
    generated_at: str
    period_days: int
    totals: dict = field(default_factory=dict)
    top_undercuts: list[dict] = field(default_factory=list)
    most_volatile: list[dict] = field(default_factory=list)
    biggest_movers: list[dict] = field(default_factory=list)
    forecast_summary: dict = field(default_factory=dict)
    forecast_accuracy: list[dict] = field(default_factory=list)
    data_quality: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    def all_numbers(self) -> set[float]:
        import re

        number_re = re.compile(r"\d+(?:\.\d+)?")
        found: set[float] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, bool):
                return
            elif isinstance(node, (int, float)):
                found.add(round(float(node), 2))
            elif isinstance(node, str):
                for raw in number_re.findall(node):
                    try:
                        found.add(round(float(raw), 2))
                    except ValueError:
                        continue

        walk(self.as_dict())
        return found


_TOTALS_SQL = """
select
    (select count(*) from products)                                     as products_tracked,
    (select count(*) from retailers)                                    as retailers_tracked,
    (select count(*) from price_events
      where observed_at >= now() - cast(:period as interval))           as price_events_this_period,
    (select count(*) from analytics_marts.mart_undercut_alerts)         as active_undercuts,
    (select count(*) from analytics_marts.mart_price_volatility)        as series_with_volatility
"""

_UNDERCUTS_SQL = """
select product_name, retailer_name, currency,
       our_price, competitor_price, gap_pct, severity, confidence, days_stale
from analytics_marts.mart_undercut_alerts
order by gap_pct
limit :limit
"""

_VOLATILITY_SQL = """
select title, retailer_name, currency, mean_price, min_price, max_price,
       coefficient_of_variation, volatility_band, observation_count
from analytics_marts.mart_price_volatility
order by coefficient_of_variation desc nulls last
limit :limit
"""

_MOVERS_SQL = """
select title, retailer_name, currency, close_price, prev_price, change_pct, observed_date
from analytics_marts.mart_price_trend
where change_pct is not null
  and observed_date >= current_date - cast(:days as int)
order by abs(change_pct) desc
limit :limit
"""

_FORECAST_SUMMARY_SQL = """
select count(*)                              as forecast_rows,
       count(distinct product_id)            as products_forecast,
       min(forecast_for)                     as horizon_start,
       max(forecast_for)                     as horizon_end
from forecasts
where trained_at = (select max(trained_at) from forecasts)
"""

_ACCURACY_SQL = """
select model, count(*) as series, round(avg(mape), 2) as avg_mape,
       round(max(mape), 2) as worst_mape
from forecast_accuracy
where evaluated_at = (select max(evaluated_at) from forecast_accuracy)
group by model
order by avg_mape
"""

_QUALITY_SQL = """
select
    (select count(*) from product_matches where status = 'pending')  as matches_pending_review,
    (select count(*) from product_matches where status = 'approved') as matches_approved,
    (select max(observed_at)::date::text from price_events)          as latest_observation,
    (select count(*) from ingestion_runs
      where status = 'failed'
        and started_at >= now() - cast(:period as interval))         as failed_runs
"""


def collect_weekly_facts(session: Session, period_days: int = 7) -> WeeklyFacts:
    period = f"{period_days} days"

    totals = dict(session.execute(text(_TOTALS_SQL), {"period": period}).mappings().one())
    totals = {k: int(v) if v is not None else 0 for k, v in totals.items()}

    undercuts = [
        {
            "product_name": r["product_name"],
            "retailer_name": r["retailer_name"],
            "currency": r["currency"],
            "our_price": _d(r["our_price"]),
            "competitor_price": _d(r["competitor_price"]),
            "gap_pct": _d(r["gap_pct"]),
            "severity": r["severity"],
            "confidence": r["confidence"],
            "days_stale": int(r["days_stale"]),
        }
        for r in session.execute(text(_UNDERCUTS_SQL), {"limit": TOP_N}).mappings().all()
    ]

    volatile = [
        {
            "title": r["title"],
            "retailer_name": r["retailer_name"],
            "currency": r["currency"],
            "mean_price": _d(r["mean_price"]),
            "min_price": _d(r["min_price"]),
            "max_price": _d(r["max_price"]),
            "coefficient_of_variation": _d(r["coefficient_of_variation"]),
            "volatility_band": r["volatility_band"],
            "observation_count": int(r["observation_count"]),
        }
        for r in session.execute(text(_VOLATILITY_SQL), {"limit": TOP_N}).mappings().all()
    ]

    movers = [
        {
            "title": r["title"],
            "retailer_name": r["retailer_name"],
            "currency": r["currency"],
            "close_price": _d(r["close_price"]),
            "prev_price": _d(r["prev_price"]),
            "change_pct": _d(r["change_pct"]),
            "observed_date": r["observed_date"].isoformat(),
        }
        for r in session.execute(text(_MOVERS_SQL), {"days": period_days, "limit": TOP_N})
        .mappings()
        .all()
    ]

    forecast_row = session.execute(text(_FORECAST_SUMMARY_SQL)).mappings().one()
    forecast_summary = {
        "forecast_rows": int(forecast_row["forecast_rows"] or 0),
        "products_forecast": int(forecast_row["products_forecast"] or 0),
        "horizon_start": (
            forecast_row["horizon_start"].isoformat() if forecast_row["horizon_start"] else None
        ),
        "horizon_end": (
            forecast_row["horizon_end"].isoformat() if forecast_row["horizon_end"] else None
        ),
    }

    accuracy = [
        {
            "model": r["model"],
            "series": int(r["series"]),
            "avg_mape": _d(r["avg_mape"]),
            "worst_mape": _d(r["worst_mape"]),
        }
        for r in session.execute(text(_ACCURACY_SQL)).mappings().all()
    ]

    quality = dict(session.execute(text(_QUALITY_SQL), {"period": period}).mappings().one())
    quality = {
        "matches_pending_review": int(quality["matches_pending_review"] or 0),
        "matches_approved": int(quality["matches_approved"] or 0),
        "latest_observation": quality["latest_observation"],
        "failed_runs": int(quality["failed_runs"] or 0),
    }

    facts = WeeklyFacts(
        generated_at=datetime.now(UTC).date().isoformat(),
        period_days=period_days,
        totals=totals,
        top_undercuts=undercuts,
        most_volatile=volatile,
        biggest_movers=movers,
        forecast_summary=forecast_summary,
        forecast_accuracy=accuracy,
        data_quality=quality,
    )
    log.info("brief.facts_collected", undercuts=len(undercuts), movers=len(movers))
    return facts
