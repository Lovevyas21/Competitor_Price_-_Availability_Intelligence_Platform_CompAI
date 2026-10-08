# Competitor Price & Availability Intelligence Platform

[![CI](https://github.com/Lovevyas21/Competitor_Price_-_Availability_Intelligence_Platform_CompAI/actions/workflows/ci.yml/badge.svg)](https://github.com/Lovevyas21/Competitor_Price_-_Availability_Intelligence_Platform_CompAI/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![dbt](https://img.shields.io/badge/dbt-1.10-FF694B)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791)

A data platform that tracks competitor prices and stock across retailers, works out
who is undercutting you, forecasts where prices are heading, and sends a weekly
pricing brief.

**Live demo:** https://api-production-46f4.up.railway.app/showcase

## Features

- **Multi-source ingestion** from public product price APIs, with rate limiting,
  retries and a dead-letter queue.
- **Raw-first storage.** Every API response is saved to a bronze layer (local disk or
  S3) before parsing, so the warehouse can be rebuilt without calling any API again.
- **Change data capture.** A price is stored only when it changes, with idempotency keys
  so replays never write duplicates.
- **dbt models** going from staging to intermediate to marts, with data quality tests on
  every build.
- **Undercut alerts** to Slack or email, with deduplication and a cooldown.
- **Per-SKU forecasting** with statsforecast (AutoETS / AutoARIMA against a
  seasonal-naive baseline), picked per series on backtested error.
- **Product matching** with vector embeddings in pgvector, plus a Streamlit screen for
  reviewing borderline matches.
- **Weekly pricing brief** written by an LLM (CrewAI). It's checked so that every number
  in it must exist in the warehouse data.
- **REST API** with FastAPI, plus an interactive walkthrough of the pipeline at
  `/showcase`.

## Architecture

```mermaid
flowchart LR
    SRC[Price APIs<br/>Open Prices, Fake Store] --> ING[Ingestion<br/>rate limit, retry]
    ING --> BRZ[(Bronze<br/>raw JSON)]
    ING --> CDC[CDC<br/>insert on change]
    CDC --> PG[(PostgreSQL<br/>+ pgvector)]
    PG --> DBT[dbt marts]
    DBT --> API[FastAPI]
    DBT --> FC[Forecasting]
    DBT --> AL[Alerts<br/>Slack, email]
    DBT --> BR[Weekly brief<br/>CrewAI]
    PG --> MT[Product matching]
    BEAT[Celery Beat] -. schedules .-> ING
    BEAT -.-> DBT
    BEAT -.-> FC
    BEAT -.-> AL
```

Celery workers run ingestion and the downstream jobs on a schedule, with Redis as the
broker. Postgres holds the event history and the marts. The API, the alerting service
and the brief all read from the same dbt marts, so they always agree on the numbers.

## Tech stack

| Area | Tools |
|---|---|
| Language | Python 3.12 |
| Storage | PostgreSQL 16, pgvector, S3-compatible object storage |
| Orchestration | Celery, Celery Beat, Redis |
| Transformation | dbt (dbt-postgres), Polars, Pandera |
| Data access | SQLAlchemy 2.0, Alembic, Pydantic v2 |
| Forecasting | statsforecast |
| AI | CrewAI, Gemini (via LiteLLM), fastembed |
| API / UI | FastAPI, Uvicorn, Streamlit |
| Infrastructure | Docker, Railway, Terraform (AWS), GitHub Actions |

## Project structure

```
app/
  ai/           facts, LLM brief, numeric guard, product matching, chat
  alerting/     undercut alert service and delivery channels
  api/          FastAPI app and dependencies
  clients/      one client per data source behind a common interface
  core/         settings, logging, database session
  forecasting/  dataset building, training, backtesting
  ingestion/    runner, bronze store, CDC, rate limiting, Celery tasks
  models/       domain models and validation
  showcase/     pipeline walkthrough UI
  ui/           Streamlit match review
dbt/            staging, intermediate and mart models
migrations/     Alembic migrations
infra/          Terraform (persistent and ephemeral AWS stacks)
scripts/        deployment and report scripts
tests/          unit, contract and integration tests
docs/           architecture decision records and project report
```

## Getting started

### Prerequisites

- Python 3.12
- Docker and Docker Compose
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

```bash
git clone https://github.com/Lovevyas21/Competitor_Price_-_Availability_Intelligence_Platform_CompAI.git
cd Competitor_Price_-_Availability_Intelligence_Platform_CompAI

uv venv
uv pip install -e ".[dev,matching,ai,transform]"

cp .env.example .env
docker compose up -d db redis
alembic upgrade head
```

### Configuration

Settings are read from environment variables or `.env`. The defaults work with the
local Docker setup. The variables you're most likely to change:

| Variable | Purpose |
|---|---|
| `DATABASE_URL_OVERRIDE` | Full Postgres URL for a hosted database |
| `REDIS_URL` | Celery broker and cache |
| `BRONZE_BACKEND` | `local` or `s3` |
| `BRONZE_S3_BUCKET` / `BRONZE_S3_ENDPOINT_URL` | Object storage for raw payloads |
| `LLM_MODEL` / `GEMINI_API_KEY` | Enables the LLM brief, e.g. `gemini/gemini-3.5-flash` |
| `API_KEY` | Turns on `X-API-Key` authentication for the API |
| `SLACK_WEBHOOK_URL` | Alert delivery to Slack |
| `SHOWCASE_ENABLED` | Serves `/showcase` outside dev |

The full list is in [`app/core/settings.py`](app/core/settings.py).

## Usage

### Ingest data

```bash
python -m app.cli sources                         # list configured sources
python -m app.cli seed openprices --limit 25      # pick the best-tracked SKUs
python -m app.cli ingest openprices --seeds       # full history for seeded SKUs
python -m app.cli ingest openprices --limit 300   # recent prices across many SKUs
python -m app.cli status                          # warehouse summary
python -m app.cli replay openprices 2026-08-29    # rebuild a day from bronze
```

### Run the pipeline

```bash
make worker      # Celery worker
make beat        # Celery scheduler
make dbt-build   # build and test the dbt models
make api         # API at http://localhost:8000/docs
```

Other targets: `make forecast`, `make alerts`, `make match`, `make review`,
`make brief`, `make showcase`, `make flower`. Run `make test` for the test suite.

### API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Service and database status |
| GET | `/products` | Tracked products |
| GET | `/prices/{product_id}` | Price history for a product |
| GET | `/forecasts/{product_id}` | Forecast for a product |
| GET | `/undercuts` | Current competitor undercuts |
| GET | `/alerts` | Alerts that have been sent |
| GET | `/matches/review` | Product matches waiting for review |

Interactive docs are at `/docs`. When `API_KEY` is set, every endpoint except `/health`
needs an `X-API-Key` header.

### Scheduled jobs

All times are UTC and come from [`app/celery_app.py`](app/celery_app.py).

| Schedule | Job |
|---|---|
| Every 6 hours | Refresh tier 1 SKUs, evaluate alerts |
| Daily 01:15 | Broad price discovery |
| Daily 01:45 | Rebuild dbt marts |
| Daily 02:15 | Refresh product matches |
| Daily 02:30 | Refresh tier 2 SKUs |
| Daily 03:00 | Train forecasts |
| Sunday 04:00 | Refresh tier 3 SKUs |
| Monday 06:00 | Generate the weekly brief |
| 25th of each month | Create upcoming table partitions |

## Data model

- `price_events` and `stock_events` are append-only and partitioned by month on
  `observed_at`.
- `product_versions` is an SCD Type 2 dimension, with exactly one current row per
  product.
- Every event has an idempotency key, so re-running a load never duplicates history.
- Prices are compared only within the same currency. Currency is part of the grain of
  every mart.

| Mart | What it answers |
|---|---|
| `mart_undercut_alerts` | Who is undercutting us, by how much, and how fresh the evidence is |
| `mart_price_gap_vs_own` | How competitor prices compare with our catalogue |
| `mart_price_trend` | Daily price series and day-over-day change |
| `mart_price_volatility` | Which SKUs move the most |
| `mart_out_of_stock_frequency` | Out-of-stock rate per SKU and retailer |

## Testing

```bash
docker compose up -d db redis
pytest
```

The suite has unit, contract and integration tests. The integration tests run against
a real Postgres and Redis. CI runs linting (ruff), the tests, `dbt build`, Terraform
validation and a Docker image build on every push.

## Deployment

The app runs on [Railway](https://railway.com) as three services built from the same
Dockerfile:

| Service | Command |
|---|---|
| `api` | `uvicorn app.api.main:app --host 0.0.0.0 --port $PORT` |
| `worker` | `celery -A app.celery_app worker -Q ingest,default,maintenance` |
| `beat` | `celery -A app.celery_app beat` |

These sit alongside Postgres with pgvector, Redis and an S3-compatible bucket for the
bronze layer. Each deploy runs `alembic upgrade head` and `dbt build` before the new
version goes live.

An AWS setup (VPC, RDS, EC2, S3, SSM, IAM) is also included as Terraform in
[`infra/`](infra/), with scripts to create and destroy it on demand. See
[`infra/README.md`](infra/README.md).

## Documentation

- [Architecture decision records](docs/adr/)
- [Sample weekly brief](docs/demo/sample-weekly-brief.md)
