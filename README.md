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
| 3 | dbt staging -> marts, data quality tests | Next |
| 4 | statsforecast forecasting, FastAPI, alerts, Metabase | Planned |
| 5 | pgvector matching, Streamlit review UI, CrewAI brief | Planned |
| 6 | Terraform / RDS / EC2 / S3, CI-CD | Planned |

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
