# Competitor Price & Availability Intelligence Platform

Near-real-time competitor price and stock tracking: multi-source ingestion with
change data capture, dbt marts, per-SKU forecasting, undercut alerting, and an
LLM agent crew that writes a weekly pricing brief.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Repo, Docker, schema + migrations, config, logging | **Done** |
| 1 | Keyless ingestion (Fake Store, Open Prices), bronze store, CDC | **Done** |
| 2 | Celery + Beat, rate limiting, DLQ, Flower | **Done** |
| 3 | dbt staging -> marts, data quality tests | **Done** |
| 4 | statsforecast forecasting, FastAPI, alerts, Metabase | **Done** |
| 5 | pgvector matching, Streamlit review UI, CrewAI brief | **Done** |
| 6 | Terraform / RDS / EC2 / S3, CI-CD | **Done** (written, not applied) |

## Demo assets

Measured results, architecture diagrams, a real generated brief, tested dashboard
queries, and portfolio material live in [`docs/demo/`](docs/demo/). Every figure there
was read from the running system — including the limitations.

## Quick start

```bash
python -m pip install uv
python -m uv venv
python -m uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
cp .env.example .env
docker compose up -d          # postgres + redis only
.venv/Scripts/python.exe -m alembic upgrade head
```

Requires Docker Desktop running. Verify:

```bash
docker compose exec db psql -U cpi -d cpi -c "\dt"
```

## Using it

```bash
python -m app.cli sources                          # what's wired up
python -m app.cli seed openprices --limit 25       # pick best-tracked SKUs
python -m app.cli ingest openprices --seeds        # deep: full history per SKU
python -m app.cli ingest openprices --limit 300    # broad: recent feed
python -m app.cli status                           # warehouse summary
```

`--seeds` is the deep path (one call per SKU, ~100 dated observations each);
plain `ingest` is the broad path (many SKUs, one price each). See ADR-001.

## Running the pipeline

Docker runs only the two stateful services. The worker, Beat and Flower run from the
local venv, which keeps the container count -- and memory -- down on a constrained
machine. See ADR-006.

```bash
docker compose up -d     # postgres + redis
make worker              # celery worker
make beat                # celery beat
```

To exercise the production image instead, run them as containers:

```bash
docker compose --profile workers up -d --build
```

## Transformations (dbt)

```bash
make dbt-deps     # once
make dbt-build    # models + seeds + tests
```

Layers: `staging/` (clean, typed) -> `intermediate/` (joins, daily grain) ->
`marts/` (business questions). `dbt build` runs models and tests together, so a mart
that goes wrong fails the run instead of quietly serving bad numbers.

| Mart | Answers |
|---|---|
| `mart_price_volatility` | which SKUs move most (coefficient of variation) |
| `mart_price_gap_vs_own` | how competitor prices compare to our catalogue |
| `mart_undercut_alerts` | who is undercutting us, how badly, how fresh the evidence |
| `mart_price_trend` | daily series + day-over-day change (feeds forecasting) |
| `mart_out_of_stock_frequency` | OOS rate per SKU/retailer |

Two things worth knowing:

- **Prices span five currencies, and are never compared across them.** Currency is part
  of the grain everywhere and the gap mart joins on UPC *and* currency. See ADR-008.
- **`mart_out_of_stock_frequency` returns zero rows today.** Neither keyless source
  publishes availability. It is built against the real schema so it works the moment a
  stock-bearing source (Best Buy, Digi-Key) is connected.

Marts are also rebuilt automatically after the daily ingestion sweep, via the
`build_marts` Celery task.

## Serving, forecasting and alerts

```bash
make api        # http://localhost:8000/docs
make forecast   # nightly training, on demand
make alerts     # evaluate undercuts and deliver new ones
make metabase   # opt-in BI at http://localhost:3000
```

Endpoints: `/health`, `/products`, `/prices/{id}`, `/forecasts/{id}`, `/undercuts`,
`/alerts`, `/matches/review`. Auth is an `X-API-Key` header, enabled by setting
`API_KEY`; when unset the API is open and `/health` says so.

## Walkthrough

```bash
make showcase   # http://localhost:8000/showcase
```

A guided tour of the pipeline for people who would rather see it than read about it. It
walks the five stages -- connect, extract, resolve, compare, decide -- revealing each
one line by line in a console.

Every figure it prints is queried live at the moment you press run; the stage timings in
the rail are real elapsed milliseconds. Only the pacing is theatre, and it happens in the
browser after the data has already arrived, so the server never sleeps to look busy.
`skip` renders the whole run instantly.

It reads real mart data and is deliberately **not** behind the API key, so it serves in
dev only by default. A demo deployment opts in with `SHOWCASE_ENABLED=true`.

### Forecasting

statsforecast (AutoETS / AutoARIMA) with a seasonal-naive baseline that always competes
and only loses on a strict improvement. Champions are chosen per series on **backtested**
MAPE, and every candidate's score is stored so selection stays auditable.

Two deliberate constraints, both of which lower the headline numbers on purpose
(ADR-009):

- **Scoring ignores forward-filled days.** Series are filled to a daily grid so models
  see a regular frequency, but grading on filled rows measures the fill, not the
  forecast. Correcting this moved reported MAPE from a flattering 0.15% to a real ~3.16%.
- **Stale series are not forecast.** A 7-day horizon projected from a series last seen
  18 months ago yields predictions dated in the past.

With the current keyless source that leaves 4 forecastable series out of 22, each scored
on only a handful of observed points -- too thin to trust a per-series MAPE. The pipeline
is correct; the data is sparse. A daily-refresh retail API is what makes it meaningful.

### Alerting

The undercut rule lives in `mart_undercut_alerts` (dbt), so it is tested with the marts
and shared by the API, the dashboard and the alert. The service adds what SQL cannot:
deduplication (an undercut persisting a week is one alert, not 28 -- but a *deeper* cut
is new), a staleness gate so old evidence is recorded without paging anyone, and
`sent_at` written only after delivery succeeds so a webhook outage retries rather than
silently dropping.

## Matching and the weekly brief

```bash
make match     # embed products, generate candidate matches
make review    # human review UI at http://localhost:8501
make brief     # weekly pricing brief (Markdown)
```

### Product matching

Embeddings use **fastembed** (ONNX) rather than sentence-transformers: the same
`all-MiniLM-L6-v2` 384-dim model the build document specifies, without pulling in torch
(~2.5GB) on a memory-constrained machine.

Policy, in priority order:

1. **Exact UPC/MPN wins outright.** An identifier is a fact; a cosine score is an opinion.
2. **Blocking before vector search** (same category), which cuts comparisons and
   suppresses the classic false positive on similarly-shaped names.
3. **Three bands:** `>= 0.92` auto-match, `0.80-0.92` human review, `< 0.80` rejected.

Every decision is stored with its method and score, and human verdicts are recorded with
reviewer and timestamp -- that is the label set precision and recall get measured against
later, rather than assumed.

### Weekly brief

Deterministic by default: `ai/facts.py` pulls a closed set of numbers from the marts and
`ai/brief.py` renders them. No key, no cost, nothing to fabricate.

With `LLM_MODEL` set, a CrewAI crew narrates the *same* facts -- and the output must pass
`ai/guard.py`, which requires **every number in the brief to exist in the facts**. Any
unsupported figure discards the LLM version and falls back to the deterministic one. The
worst case is a plainer brief, never a wrong one. See ADR-010.

## Deployment

The full AWS stack is written as Terraform in [`infra/`](infra/) — VPC, private RDS,
Graviton EC2, S3 bronze with lifecycle tiering, SSM secrets, least-privilege IAM, and
budget alarms.

**It has not been applied.** Phase 6 is the only phase that costs money (~$28-36/month),
and nothing in the project needs AWS to be demonstrated. The configuration is verified
with `terraform fmt`, `init -backend=false` and `validate`, all of which run in CI
without an AWS account. `terraform plan` has never run, so a first apply should be
expected to surface real issues validation cannot catch. See ADR-011.

```bash
cd infra && terraform init -backend=false && terraform validate
```

CI (`.github/workflows/ci.yml`) runs lint, format check, migrations, the full test suite
against pgvector + Redis services, `dbt build`, Terraform validation, and a production
image build. Deploy is `workflow_dispatch` only, behind a typed confirmation, using OIDC
role assumption and SSM Run Command -- no stored AWS keys, no open SSH port.

### Rebuilding from bronze

Every raw payload is stored before parsing, so the warehouse is reproducible. If the
database is lost, replay rebuilds it with **no upstream traffic and no quota spend**:

```bash
python -m app.cli replay openprices 2026-08-29
```

This is not theoretical -- the local Postgres volume was lost to a Docker storage
fault and rebuilt from bronze in 30 seconds (3,420 events across 111 partitions).

Flower is **opt-in and runs from the local venv**, not as a container -- it is a
debugging tool, and a dedicated container would hold memory permanently on a
RAM-constrained machine for something used occasionally:

```bash
make flower    # http://localhost:5555
```

Schedules (UTC), defined in `app/celery_app.py`:

| When | Task |
|---|---|
| every 6h | tier-1 SKU refresh |
| 02:30 daily | tier-2 refresh |
| 04:00 Sunday | tier-3 refresh |
| 01:15 daily | broad discovery sweep |
| 25th monthly | pre-create partitions |

Backfill without touching the upstream API (re-parses stored raw payloads):

```bash
python -m app.cli replay openprices 2026-08-29
```

## Layout

```
app/
  clients/      # per-source API clients behind a common interface
  ingestion/    # tasks, rate limiting, CDC
  models/       # pydantic v2 + SQLAlchemy 2.0
  forecasting/  # train, backtest
  ai/           # crew, tools, matching
  api/          # FastAPI
  core/         # settings, logging, db
dbt/            # staging | intermediate | marts
infra/          # terraform
migrations/     # alembic
docs/adr/       # architecture decision records
```

## Design notes

- `price_events` / `stock_events` are append-only and **monthly range-partitioned** on
  `observed_at`. `ensure_month_partition(parent, month_start)` creates partitions on demand.
- `product_versions` is an **SCD Type 2** dimension; a partial unique index enforces exactly
  one current row per product.
- Every event carries an `idempotency_key`, uniquely indexed with `observed_at`, so replays
  and late-arriving duplicates cannot double-write history.
- Raw payloads are persisted **before** parsing, so any parse bug is replayable.
- No PII is collected; all data is public product data.

See `docs/adr/` for decisions and their trade-offs.
