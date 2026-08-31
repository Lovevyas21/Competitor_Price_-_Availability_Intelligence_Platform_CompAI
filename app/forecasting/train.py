"""Nightly per-SKU price forecasting.

Model choice follows the build document: **statsforecast** (AutoETS / AutoARIMA) as the
per-SKU baseline, for speed and built-in prediction intervals.

Two decisions worth stating, because they are what separate a forecast you can act on
from a number on a dashboard:

* **A naive baseline always runs.** `SeasonalNaive` (here, last-value) is the honest
  benchmark. Retail prices are close to a random walk, so a sophisticated model that
  cannot beat "tomorrow looks like today" is not earning its keep -- and without the
  baseline you would never know.

* **Accuracy is measured by backtesting, not by fit.** `cross_validation` refits on
  successive windows and scores predictions the model never saw. In-sample error would
  flatter every model and be useless for choosing between them.

The champion is selected per series on backtested MAPE, and falls back to the baseline
whenever it fails to beat it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.forecasting.dataset import build_dataset

log = get_logger(__name__)

DEFAULT_HORIZON = 7
#: Prediction interval, in percent. 80 is the usual planning band.
CONFIDENCE_LEVEL = 80
#: Backtest windows. More windows is a steadier estimate but costs refits.
CV_WINDOWS = 3

BASELINE_MODEL = "SeasonalNaive"


@dataclass
class TrainingStats:
    series_considered: int = 0
    series_forecast: int = 0
    forecasts_written: int = 0
    accuracy_rows_written: int = 0
    champions: dict[str, int] = field(default_factory=dict)
    skipped_too_short: int = 0

    def as_dict(self) -> dict:
        return {
            "series_considered": self.series_considered,
            "series_forecast": self.series_forecast,
            "forecasts_written": self.forecasts_written,
            "accuracy_rows_written": self.accuracy_rows_written,
            "champions": self.champions,
            "skipped_too_short": self.skipped_too_short,
        }


def _models(season_length: int = 7):
    """Champion candidates plus the baseline they must beat."""
    from statsforecast.models import AutoARIMA, AutoETS, SeasonalNaive  # noqa: PLC0415

    return [
        AutoETS(season_length=season_length),
        AutoARIMA(season_length=season_length),
        SeasonalNaive(season_length=season_length),
    ]


def mape(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    """Mean absolute percentage error, ignoring zero actuals.

    A zero price makes the percentage undefined rather than infinite; dropping those
    points is preferable to letting one free item produce an inf that poisons the mean.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    usable = actual != 0
    if not usable.any():
        return None
    return float(np.mean(np.abs((actual[usable] - predicted[usable]) / actual[usable])) * 100)


def backtest(dataset: pd.DataFrame, horizon: int = DEFAULT_HORIZON) -> pd.DataFrame:
    """Rolling-origin cross-validation. Returns per-series, per-model MAPE.

    **Scored only on genuinely observed days.** The daily grid is forward-filled so the
    models see a regular frequency, but a filled day just repeats the previous price --
    scoring those rows would mean grading every model largely on "did it copy the last
    value", which flatters all of them and makes the naive baseline look near-perfect.
    Filtering to observed points measures whether a model actually anticipated a change.
    """
    from statsforecast import StatsForecast  # noqa: PLC0415

    fit_frame = dataset[["unique_id", "ds", "y"]]
    sf = StatsForecast(models=_models(), freq="D", n_jobs=1)
    cv = sf.cross_validation(df=fit_frame, h=horizon, step_size=horizon, n_windows=CV_WINDOWS)
    cv = cv.reset_index() if cv.index.name == "unique_id" else cv

    if "is_observed" in dataset.columns:
        observed = dataset.loc[dataset["is_observed"], ["unique_id", "ds"]]
        before = len(cv)
        cv = cv.merge(observed, on=["unique_id", "ds"], how="inner")
        log.info("forecast.backtest_scored_on_observed", kept=len(cv), of=before)

    model_columns = [c for c in cv.columns if c not in ("unique_id", "ds", "cutoff", "y")]

    scores: list[dict] = []
    for unique_id, group in cv.groupby("unique_id", sort=False):
        for model in model_columns:
            score = mape(group["y"].to_numpy(), group[model].to_numpy())
            if score is not None:
                scores.append(
                    {
                        "unique_id": unique_id,
                        "model": model,
                        "mape": score,
                        "scored_points": int(len(group)),
                    }
                )

    return pd.DataFrame(scores)


def pick_champions(scores: pd.DataFrame) -> dict[str, str]:
    """Lowest backtested MAPE wins; ties and failures fall back to the baseline."""
    if scores.empty:
        return {}

    champions: dict[str, str] = {}
    for unique_id, group in scores.groupby("unique_id", sort=False):
        ranked = group.sort_values("mape", ascending=True)
        best = ranked.iloc[0]
        baseline = group[group["model"] == BASELINE_MODEL]

        # Only displace the baseline on a genuine improvement.
        if not baseline.empty and best["mape"] >= float(baseline.iloc[0]["mape"]):
            champions[unique_id] = BASELINE_MODEL
        else:
            champions[unique_id] = str(best["model"])
    return champions


def forecast_all(dataset: pd.DataFrame, horizon: int = DEFAULT_HORIZON) -> pd.DataFrame:
    """Fit on full history and predict `horizon` days ahead, with intervals."""
    from statsforecast import StatsForecast  # noqa: PLC0415

    sf = StatsForecast(models=_models(), freq="D", n_jobs=1)
    predictions = sf.forecast(
        df=dataset[["unique_id", "ds", "y"]], h=horizon, level=[CONFIDENCE_LEVEL]
    )
    return predictions.reset_index() if predictions.index.name == "unique_id" else predictions


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
_INSERT_FORECAST = """
insert into forecasts
  (product_id, model, horizon_days, yhat, yhat_lower, yhat_upper, forecast_for, trained_at)
select * from unnest(
  cast(:product_id as bigint[]), cast(:model as text[]), cast(:horizon_days as int[]),
  cast(:yhat as numeric[]), cast(:yhat_lower as numeric[]), cast(:yhat_upper as numeric[]),
  cast(:forecast_for as date[]), cast(:trained_at as timestamptz[])
)
"""

_INSERT_ACCURACY = """
insert into forecast_accuracy (product_id, model, mape, horizon_days, evaluated_at)
select * from unnest(
  cast(:product_id as bigint[]), cast(:model as text[]), cast(:mape as numeric[]),
  cast(:horizon_days as int[]), cast(:evaluated_at as timestamptz[])
)
"""


def persist_accuracy(
    session: Session, scores: pd.DataFrame, horizon: int, evaluated_at: datetime
) -> int:
    """Store every model's backtested MAPE, not just the winner's.

    Keeping the losers is what makes champion selection auditable later, and it is how
    you notice a model quietly degrading across runs.
    """
    if scores.empty:
        return 0

    product_ids, models, mapes = [], [], []
    for row in scores.itertuples():
        product_ids.append(int(row.unique_id.split("|")[0]))
        models.append(str(row.model))
        mapes.append(round(float(row.mape), 3))

    session.execute(
        text(_INSERT_ACCURACY),
        {
            "product_id": product_ids,
            "model": models,
            "mape": mapes,
            "horizon_days": [horizon] * len(models),
            "evaluated_at": [evaluated_at] * len(models),
        },
    )
    return len(models)


def persist_forecasts(
    session: Session,
    predictions: pd.DataFrame,
    champions: dict[str, str],
    horizon: int,
    trained_at: datetime,
) -> int:
    """Write only the champion model's predictions per series."""
    if predictions.empty:
        return 0

    lo_suffix, hi_suffix = f"-lo-{CONFIDENCE_LEVEL}", f"-hi-{CONFIDENCE_LEVEL}"
    cols: dict[str, list] = {
        k: []
        for k in (
            "product_id",
            "model",
            "horizon_days",
            "yhat",
            "yhat_lower",
            "yhat_upper",
            "forecast_for",
            "trained_at",
        )
    }

    def _clean(value) -> float | None:
        return None if value is None or pd.isna(value) else round(float(value), 2)

    for _, row in predictions.iterrows():
        unique_id = str(row["unique_id"])
        model = champions.get(unique_id, BASELINE_MODEL)
        if model not in predictions.columns or pd.isna(row[model]):
            continue

        cols["product_id"].append(int(unique_id.split("|")[0]))
        cols["model"].append(model)
        cols["horizon_days"].append(horizon)
        cols["yhat"].append(_clean(row[model]))
        # Intervals are optional: a model may not produce them for a given series.
        lo, hi = model + lo_suffix, model + hi_suffix
        cols["yhat_lower"].append(_clean(row[lo]) if lo in predictions.columns else None)
        cols["yhat_upper"].append(_clean(row[hi]) if hi in predictions.columns else None)
        cols["forecast_for"].append(pd.Timestamp(row["ds"]).date())
        cols["trained_at"].append(trained_at)

    if not cols["product_id"]:
        return 0

    session.execute(text(_INSERT_FORECAST), cols)
    return len(cols["product_id"])


def train_and_forecast(session: Session, horizon: int = DEFAULT_HORIZON) -> TrainingStats:
    """Full nightly run: build dataset, backtest, pick champions, forecast, persist."""
    stats = TrainingStats()
    dataset = build_dataset(session)

    if dataset.empty:
        log.warning("forecast.no_series")
        return stats

    stats.series_considered = int(dataset["unique_id"].nunique())
    now = datetime.now(UTC)

    scores = backtest(dataset, horizon=horizon)
    champions = pick_champions(scores)
    stats.champions = {
        model: list(champions.values()).count(model) for model in set(champions.values())
    }

    predictions = forecast_all(dataset, horizon=horizon)
    stats.series_forecast = int(predictions["unique_id"].nunique()) if not predictions.empty else 0

    stats.accuracy_rows_written = persist_accuracy(session, scores, horizon, now)
    stats.forecasts_written = persist_forecasts(session, predictions, champions, horizon, now)

    log.info("forecast.trained", **stats.as_dict())
    return stats
