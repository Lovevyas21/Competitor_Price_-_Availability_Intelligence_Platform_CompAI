"""Turn stored price history into forecastable series.

Two things make retail price data awkward for time-series models, and both are handled
here rather than being left to surprise the model:

1. **Observations are irregular.** A crowd-sourced price appears when someone records it,
   not daily. statsforecast expects a regular frequency, so each series is resampled to a
   daily grid and forward-filled -- a price is assumed to hold until it is next observed,
   which is how shelf prices actually behave.

2. **Series are short and uneven.** A model fitted on four points will happily produce a
   confident forecast that means nothing, so series below a minimum length are excluded
   outright rather than forecast badly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)

#: Below this many observed points, a fitted model is noise dressed as a forecast.
MIN_OBSERVATIONS = 10

#: Cap how far back to pull. Very old prices say little about next week.
MAX_HISTORY_DAYS = 730

#: A series whose last observation is older than this is not forecast at all.
#: Extrapolating 7 days past a series that ended 18 months ago produces "forecasts"
#: dated in the past -- confidently wrong, and worse than no forecast.
MAX_STALENESS_DAYS = 30

SERIES_SQL = """
select
    product_id,
    retailer_id,
    currency,
    observed_date,
    close_price
from analytics_marts.mart_price_trend
where observed_date >= current_date - cast(:max_days as int)
order by product_id, retailer_id, currency, observed_date
"""


@dataclass(frozen=True)
class SeriesKey:
    """Identifies one forecastable series. Currency is part of the key -- see ADR-008."""

    product_id: int
    retailer_id: int | None
    currency: str

    @property
    def unique_id(self) -> str:
        return f"{self.product_id}|{self.retailer_id or 0}|{self.currency}"

    @classmethod
    def parse(cls, unique_id: str) -> SeriesKey:
        product_id, retailer_id, currency = unique_id.split("|")
        return cls(
            product_id=int(product_id),
            retailer_id=int(retailer_id) or None,
            currency=currency,
        )


def load_price_history(session: Session, max_days: int = MAX_HISTORY_DAYS) -> pd.DataFrame:
    rows = session.execute(text(SERIES_SQL), {"max_days": max_days}).mappings().all()
    if not rows:
        return pd.DataFrame(columns=["product_id", "retailer_id", "currency", "ds", "y"])

    frame = pd.DataFrame(rows)
    frame = frame.rename(columns={"observed_date": "ds", "close_price": "y"})
    frame["ds"] = pd.to_datetime(frame["ds"])
    frame["y"] = frame["y"].astype(float)
    return frame


def to_regular_daily(
    frame: pd.DataFrame,
    min_observations: int = MIN_OBSERVATIONS,
    max_staleness_days: int | None = MAX_STALENESS_DAYS,
) -> pd.DataFrame:
    """Resample each series onto a daily grid, forward-filling between observations.

    Returns the long format statsforecast expects -- unique_id, ds, y -- plus an
    `is_observed` flag marking rows that came from a real observation rather than the
    forward fill. Scoring must use that flag: filled rows repeat the previous value, so
    including them makes "predict the last value" look near-perfect and inflates every
    model's apparent accuracy.
    """
    if frame.empty:
        return pd.DataFrame(columns=["unique_id", "ds", "y", "is_observed"])

    frame = frame.copy()
    frame["retailer_id"] = frame["retailer_id"].fillna(0).astype(int)
    frame["unique_id"] = (
        frame["product_id"].astype(str)
        + "|"
        + frame["retailer_id"].astype(str)
        + "|"
        + frame["currency"].astype(str)
    )

    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    resampled: list[pd.DataFrame] = []
    skipped_stale = 0

    for unique_id, group in frame.groupby("unique_id", sort=False):
        observed = group.dropna(subset=["y"])
        if len(observed) < min_observations:
            continue

        # Collapse any same-day duplicates before building the grid.
        series = observed.set_index("ds")["y"].groupby(level=0).last().sort_index()

        if max_staleness_days is not None:
            age_days = (today - series.index.max()).days
            if age_days > max_staleness_days:
                skipped_stale += 1
                continue

        # Extend the grid to today, not just to the last observation. Without this a
        # series last seen a week ago is forecast from *that* day, so a 7-day horizon
        # lands on dates already in the past. Extending is consistent with the
        # forward-fill assumption: the last known price is assumed to still hold.
        grid_end = series.index.max()
        if max_staleness_days is not None:
            grid_end = max(grid_end, today)
        grid = pd.date_range(series.index.min(), grid_end, freq="D")
        daily = series.reindex(grid).ffill()

        resampled.append(
            pd.DataFrame(
                {
                    "unique_id": unique_id,
                    "ds": grid,
                    "y": daily.to_numpy(),
                    "is_observed": grid.isin(series.index),
                }
            )
        )

    if skipped_stale:
        log.info("forecast.skipped_stale_series", count=skipped_stale,
                 max_staleness_days=max_staleness_days)

    if not resampled:
        return pd.DataFrame(columns=["unique_id", "ds", "y", "is_observed"])

    out = pd.concat(resampled, ignore_index=True)
    log.info(
        "forecast.dataset_built",
        series=out["unique_id"].nunique(),
        rows=len(out),
        min_observations=min_observations,
    )
    return out


def build_dataset(
    session: Session,
    min_observations: int = MIN_OBSERVATIONS,
    max_days: int = MAX_HISTORY_DAYS,
    max_staleness_days: int | None = MAX_STALENESS_DAYS,
) -> pd.DataFrame:
    return to_regular_daily(
        load_price_history(session, max_days), min_observations, max_staleness_days
    )
