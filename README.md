# Competitor Price & Availability Intelligence Platform

Near-real-time competitor price and stock tracking: multi-source ingestion with
change data capture, dbt marts, per-SKU forecasting, undercut alerting, and an
LLM agent crew that writes a weekly pricing brief.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Repo, Docker, schema + migrations, config, logging | **Done** |
| 1 | Keyless ingestion (Fake Store, Open Food Facts), bronze store, CDC | Next |
| 2 | Celery + Beat, rate limiting, DLQ, real API sources | Planned |
| 3 | dbt staging -> marts, data quality tests | Planned |
| 4 | statsforecast forecasting, FastAPI, alerts, Metabase | Planned |
| 5 | pgvector matching, Streamlit review UI, CrewAI brief | Planned |
| 6 | Terraform / RDS / EC2 / S3, CI-CD | Planned |

## Quick start

```bash
python -m pip install uv
python -m uv venv
python -m uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
cp .env.example .env
docker compose up -d
.venv/Scripts/python.exe -m alembic upgrade head
```

Requires Docker Desktop running. Verify:

```bash
docker compose exec db psql -U cpi -d cpi -c "\dt"
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
