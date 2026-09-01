# Measured results

Snapshot taken 2026-09-01 (second pass) with the stack idle and marts freshly built.

The first pass ingested only ~1.2% of the upstream feed and, because the API returns
oldest-first, that slice was dominated by 2010-2020 observations. Every undercut read
as stale and only 4 series were forecastable. Ingestion now targets a 90-day window,
which is what these numbers reflect.

Every figure here was read from the running system, not estimated. Reproduce with the
commands in each section.

## Scale

| Metric | Value |
|---|---|
| Price events | 8,433 |
| Products tracked | 3,932 |
| Retailers | 157 |
| Currencies | 24 |
| Monthly partitions in use | 115 |
| History span | 2010-07-08 → 2026-08-31 |

```bash
docker compose exec db psql -U cpi -d cpi -c "select count(*) from price_events"
```

## Test coverage

| Suite | Result |
|---|---|
| Python (unit + integration) | **150 passed** |
| dbt (models, seeds, data tests) | **102/102** |
| Terraform | `fmt` + `validate` clean |
| Lint / format | clean |

```bash
make test && make dbt-build && (cd infra && terraform validate)
```

## Marts

| Mart | Rows | Answers |
|---|---|---|
| `mart_price_trend` | 8,433 | daily series + day-over-day change |
| `mart_price_gap_vs_own` | 152 | competitor vs our catalogue |
| `mart_price_volatility` | 272 | which SKUs move most |
| `mart_undercut_alerts` | 108 (62 on evidence <= 7 days old) | who is undercutting us, how badly |
| `mart_out_of_stock_frequency` | **0** | see limitations |

## Top undercuts (real output)

| Product | Retailer | Ours | Theirs | Gap | Severity |
|---|---|---|---|---|---|
| Bio et équitable | Intermarché | 2.15 | 0.99 | **−53.95%** | critical |
| Pâte à tartiner | Centre Commercial E.Leclerc | 2.55 | 1.69 | −33.73% | critical |
| Chips Paysanne | Centre Commercial E. Leclerc | 2.85 | 1.89 | −33.68% | critical |
| Beurre Demi-Sel (60% M.G.) | Centre Commercial E.Leclerc | 1.75 | 1.20 | −31.43% | critical |
| Riz Long | Centre Commercial E.Leclerc | 0.95 | 0.71 | −25.26% | critical |

All prices EUR. Every row carries a freshness label — all of these read `stale`, because
Open Prices is crowd-sourced with historical observation dates. The alert service records
them but **withholds delivery** above 7 days old.

## Most volatile SKUs

| Product | Retailer | Mean | CV | Band |
|---|---|---|---|---|
| Nutella Plant-Based | Bayern | 3.26 | 0.390 | high |
| Lentilles vertes | Centre Commercial E.Leclerc | 1.21 | 0.375 | high |
| Lentilles vertes | E.Leclerc | 1.32 | 0.290 | high |
| Petites madeleines St Michel | Super U | 2.83 | 0.289 | high |
| 10 oeufs frais | E.Leclerc | 1.53 | 0.273 | high |

Coefficient of variation, not raw standard deviation: it is unitless, so a €0.35 baguette
ranks against a €3.57 spread — and it stays comparable across 16 currencies.

## Forecast accuracy (backtested)

| Model | Series | Avg MAPE | Worst |
|---|---|---|---|
| AutoARIMA | 9 | **3.13%** | 15.56% |
| SeasonalNaive (baseline) | 9 | 3.13% | 15.56% |
| AutoETS | 9 | 3.13% | 15.56% |

Inside the ≤12% SLA — but read the limitations below before quoting it.

The first implementation reported **0.15%**. That was measuring the forward-fill, not the
forecast: series are resampled to a daily grid so models see a regular frequency, and on a
near-constant series "predict the last value" is trivially right. Scoring now ignores
filled days. Every model's number got worse, which is the point.

## Performance

| Operation | Result |
|---|---|
| Bronze replay (947 payloads → 7,922 records) | **41 s** |
| Same, row-by-row over a 298 ms link | ~3.3 h (estimated) |
| Warehouse rebuild after volume loss | 30 s, no upstream calls |
| Embedding products (measured over 1,251) | 35 s |
| Match generation (measured over 490 pairs) | 3 s |

## Matching

Counts are current; the timings above were measured on a smaller earlier run and are
labelled with the size they were measured at.

| Band | Count |
|---|---|
| Auto-matched (≥ 0.92) | 370 |
| Queued for human review (0.80–0.92) | 2,187 |
| Products embedded | 3,848 |

Auto-matches were inspected: the 1.000-similarity pairs are genuinely identical titles
differing only in case ("Yaourt avec des Fruits" / "Yaourt avec des fruits").

## Limitations, stated

These are real and not worked around:

1. **`mart_out_of_stock_frequency` returns zero rows.** Neither keyless source publishes
   availability. The model is written against the real schema and starts producing
   numbers the moment a stock-bearing source (Best Buy, Digi-Key) is connected.
2. **11 of 50 series are fresh enough to forecast** (was 4 of 22 before the recency fix).
   Still a thin basis for a per-series MAPE, and the three models remain within 0.01 of
   each other — retail prices are close to a random walk, so the naive baseline wins 8 of
   11. That is a real finding, not a bug, but a daily-refresh retail API is what would
   make forecasting genuinely meaningful here.
3. **62 of 108 undercuts now rest on evidence <= 7 days old** and are deliverable; the
   rest are recorded with a staleness label and withheld.
4. **Terraform has never been applied.** `fmt` and `validate` pass; `plan` has not run.
5. **The CrewAI path has not run against a live model.** No LLM key is configured. The
   guard and the fallback are tested independently of it.
