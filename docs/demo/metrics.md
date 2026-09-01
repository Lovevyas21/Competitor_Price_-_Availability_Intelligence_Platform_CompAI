# Measured results

Snapshot taken 2026-09-01 with the stack idle and marts freshly built.

Every figure here was read from the running system, not estimated. Reproduce with the
commands in each section.

## Scale

| Metric | Value |
|---|---|
| Price events | 3,561 |
| Products tracked | 1,448 |
| Retailers | 96 |
| Currencies | 16 |
| Monthly partitions in use | 111 |
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
| `mart_price_trend` | 3,561 | daily series + day-over-day change |
| `mart_price_gap_vs_own` | 149 | competitor vs our catalogue |
| `mart_price_volatility` | 122 | which SKUs move most |
| `mart_undercut_alerts` | 62 | who is undercutting us, how badly |
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
| AutoARIMA | 4 | **3.16%** | 5.56% |
| SeasonalNaive (baseline) | 4 | 3.17% | 5.56% |
| AutoETS | 4 | 3.17% | 5.56% |

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
| Embedding 1,251 products | 35 s |
| Match generation (490 pairs) | 3 s |

## Matching

| Band | Count |
|---|---|
| Auto-matched (≥ 0.92) | 70 |
| Queued for human review (0.80–0.92) | 461 |
| Products embedded | 1,390 |

Auto-matches were inspected: the 1.000-similarity pairs are genuinely identical titles
differing only in case ("Yaourt avec des Fruits" / "Yaourt avec des fruits").

## Limitations, stated

These are real and not worked around:

1. **`mart_out_of_stock_frequency` returns zero rows.** Neither keyless source publishes
   availability. The model is written against the real schema and starts producing
   numbers the moment a stock-bearing source (Best Buy, Digi-Key) is connected.
2. **Only 4 of 22 series are fresh enough to forecast**, each scored on a handful of
   observed points — too thin to trust a per-series MAPE. The pipeline is correct; the
   crowd-sourced source is sparse. A daily-refresh retail API is what makes it meaningful.
3. **Every undercut is stale evidence.** Recorded, surfaced with a confidence label, and
   deliberately not delivered.
4. **Terraform has never been applied.** `fmt` and `validate` pass; `plan` has not run.
5. **The CrewAI path has not run against a live model.** No LLM key is configured. The
   guard and the fallback are tested independently of it.
