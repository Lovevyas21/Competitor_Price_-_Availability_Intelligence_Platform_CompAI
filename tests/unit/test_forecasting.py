from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from app.forecasting.dataset import SeriesKey, to_regular_daily
from app.forecasting.train import BASELINE_MODEL, mape, pick_champions


def make_frame(dates, prices, product_id=1, retailer_id=2, currency="EUR"):
    return pd.DataFrame(
        {
            "product_id": product_id,
            "retailer_id": retailer_id,
            "currency": currency,
            "ds": pd.to_datetime(dates),
            "y": prices,
        }
    )


def recent_dates(n: int, step_days: int = 1):
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    return [today - timedelta(days=step_days * i) for i in range(n - 1, -1, -1)]


def test_series_key_round_trips():
    key = SeriesKey(product_id=12, retailer_id=34, currency="EUR")
    assert SeriesKey.parse(key.unique_id) == key


def test_series_key_handles_missing_retailer():
    key = SeriesKey(product_id=12, retailer_id=None, currency="SEK")
    assert key.unique_id == "12|0|SEK"
    assert SeriesKey.parse(key.unique_id).retailer_id is None


def test_gaps_are_forward_filled_onto_a_daily_grid():
    dates = recent_dates(3, step_days=5)
    out = to_regular_daily(make_frame(dates, [10.0, 12.0, 11.0]), min_observations=3)
    assert len(out) == 11
    assert out.iloc[1]["y"] == pytest.approx(10.0)


def test_filled_rows_are_marked_not_observed():
    dates = recent_dates(2, step_days=3)
    out = to_regular_daily(make_frame(dates, [10.0, 20.0]), min_observations=2)
    assert out["is_observed"].sum() == 2
    assert (~out["is_observed"]).sum() > 0


def test_series_shorter_than_minimum_is_dropped():
    out = to_regular_daily(make_frame(recent_dates(3), [1.0, 2.0, 3.0]), min_observations=10)
    assert out.empty


def test_stale_series_is_excluded():
    old = [pd.Timestamp("2024-01-01") + timedelta(days=i) for i in range(15)]
    out = to_regular_daily(make_frame(old, [10.0] * 15), min_observations=3, max_staleness_days=30)
    assert out.empty


def test_stale_series_is_kept_when_the_filter_is_disabled():
    old = [pd.Timestamp("2024-01-01") + timedelta(days=i) for i in range(15)]
    out = to_regular_daily(
        make_frame(old, [10.0] * 15), min_observations=3, max_staleness_days=None
    )
    assert not out.empty


def test_grid_is_extended_to_today_so_the_horizon_starts_now():
    dates = recent_dates(12, step_days=1)[:-3]
    out = to_regular_daily(make_frame(dates, [5.0] * 9), min_observations=3)
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    assert out["ds"].max() >= today


def test_same_day_duplicates_collapse_to_the_last_value():
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    dates = [today - timedelta(days=1), today, today]
    out = to_regular_daily(make_frame(dates, [1.0, 2.0, 3.0]), min_observations=2)
    assert out[out["ds"] == today]["y"].iloc[0] == pytest.approx(3.0)


def test_separate_currencies_are_separate_series():
    dates = recent_dates(10)
    eur = make_frame(dates, [1.0] * 10, currency="EUR")
    sek = make_frame(dates, [11.0] * 10, currency="SEK")
    out = to_regular_daily(pd.concat([eur, sek]), min_observations=5)
    assert out["unique_id"].nunique() == 2


def test_empty_input_produces_empty_output_with_schema():
    out = to_regular_daily(pd.DataFrame(), min_observations=3)
    assert out.empty
    assert list(out.columns) == ["unique_id", "ds", "y", "is_observed"]


def test_mape_is_zero_for_perfect_predictions():
    assert mape(np.array([10.0, 20.0]), np.array([10.0, 20.0])) == pytest.approx(0.0)


def test_mape_computes_percentage_error():
    assert mape(np.array([100.0]), np.array([110.0])) == pytest.approx(10.0)


def test_mape_skips_zero_actuals_instead_of_returning_inf():
    result = mape(np.array([0.0, 100.0]), np.array([5.0, 110.0]))
    assert result == pytest.approx(10.0)


def test_mape_is_none_when_every_actual_is_zero():
    assert mape(np.array([0.0, 0.0]), np.array([1.0, 2.0])) is None


def _scores(rows):
    return pd.DataFrame(rows)


def test_clearly_better_model_becomes_champion():
    scores = _scores(
        [
            {"unique_id": "1|1|EUR", "model": "AutoETS", "mape": 2.0},
            {"unique_id": "1|1|EUR", "model": BASELINE_MODEL, "mape": 9.0},
        ]
    )
    assert pick_champions(scores)["1|1|EUR"] == "AutoETS"


def test_baseline_wins_ties():
    scores = _scores(
        [
            {"unique_id": "1|1|EUR", "model": "AutoETS", "mape": 5.0},
            {"unique_id": "1|1|EUR", "model": BASELINE_MODEL, "mape": 5.0},
        ]
    )
    assert pick_champions(scores)["1|1|EUR"] == BASELINE_MODEL


def test_baseline_wins_when_the_challenger_is_worse():
    scores = _scores(
        [
            {"unique_id": "1|1|EUR", "model": "AutoARIMA", "mape": 12.0},
            {"unique_id": "1|1|EUR", "model": BASELINE_MODEL, "mape": 4.0},
        ]
    )
    assert pick_champions(scores)["1|1|EUR"] == BASELINE_MODEL


def test_champions_are_chosen_per_series():
    scores = _scores(
        [
            {"unique_id": "1|1|EUR", "model": "AutoETS", "mape": 1.0},
            {"unique_id": "1|1|EUR", "model": BASELINE_MODEL, "mape": 8.0},
            {"unique_id": "2|1|EUR", "model": "AutoETS", "mape": 9.0},
            {"unique_id": "2|1|EUR", "model": BASELINE_MODEL, "mape": 3.0},
        ]
    )
    champions = pick_champions(scores)
    assert champions["1|1|EUR"] == "AutoETS"
    assert champions["2|1|EUR"] == BASELINE_MODEL


def test_no_scores_yields_no_champions():
    assert pick_champions(pd.DataFrame()) == {}
