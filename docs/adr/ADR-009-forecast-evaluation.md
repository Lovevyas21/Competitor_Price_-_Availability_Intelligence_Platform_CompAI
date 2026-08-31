# ADR-009: Score forecasts on observed days only, and refuse to forecast stale series

**Status:** Accepted

## Context

Price observations are irregular — a crowd-sourced price appears when someone records
it. statsforecast needs a regular frequency, so each series is resampled onto a daily
grid and forward-filled (a shelf price is assumed to hold until next observed).

The first working implementation reported an average MAPE of **0.15%**, comfortably
inside the build document's ≤12% SLA. That number was worthless.

Series carry ~8.7 distinct prices spread over up to two years. Forward-filling turns
that into a mostly-constant daily series, and on a constant series "predict the last
value" is almost exactly right. The metric was measuring the fill, not forecasting
skill — and it would have been reported as evidence the models worked.

A second defect surfaced alongside it: `forecast_for` dates ranged from **2025-03-25**,
months in the past. A 7-day horizon is projected from the end of each series, so a
series last observed in March 2025 produced "forecasts" for March 2025.

## Decision

**1. Backtest scores only genuinely observed days.** The dataset carries an
`is_observed` flag; forward-filled rows are excluded before computing MAPE. Models still
*fit* on the full grid — they need the regular frequency — but they are *graded* only on
days where a real price existed.

**2. A series whose last observation is older than `MAX_STALENESS_DAYS` (30) is not
forecast at all.** Extrapolating from long-dead data produces confident predictions
about the past.

**3. The daily grid is extended to today** before forecasting, so the horizon starts now
rather than at the series' last observation. This is consistent with the forward-fill
assumption already in use.

**4. A naive baseline always competes**, and only loses on a strict improvement. Retail
prices are close to a random walk; a model that cannot beat "tomorrow looks like today"
is not earning its cost.

## Consequences

- Reported MAPE moved from 0.15% to **~3.16%** — still inside the SLA, and now
  meaningful. Every model's number rose, which is the point.
- All forecasts are future-dated (verified: 28/28 in the horizon window, all with 80%
  prediction intervals).
- Coverage dropped sharply: **18 of 22 series are excluded as stale**, leaving 4. This is
  the honest state of the data, not a regression. Open Prices is crowd-sourced and
  sparse; the build document's tier-1 six-hourly refresh against Best Buy or Digi-Key is
  what makes broad forecasting viable.
- **A limitation to state plainly:** with this data the backtest scores only ~4 observed
  points per series. That is too thin to trust a per-series MAPE, and no amount of
  modelling fixes it — it needs a denser source. The pipeline, the champion/baseline
  selection and the accuracy tracking are correct and ready; the data is not yet.
- Every candidate model's MAPE is stored, not just the winner's, so champion selection
  is auditable and degradation is visible across runs.
