PY := .venv/Scripts/python.exe

.PHONY: install up down migrate lint test fmt reset worker beat workers-docker dbt-deps dbt-build dbt-test dbt-docs api forecast alerts metabase review match brief flower logs

install:
	python -m uv pip install --python $(PY) -e ".[dev]"

up:
	docker compose up -d

down:
	docker compose down

migrate:
	$(PY) -m alembic upgrade head

lint:
	$(PY) -m ruff check .

fmt:
	$(PY) -m ruff format .

test:
	$(PY) -m pytest

reset:
	docker compose down -v && docker compose up -d

# Worker and beat run from the venv: only postgres and redis are containerised.
worker:
	$(PY) -m celery -A app.celery_app worker -l info --concurrency=2 -Q ingest,default,maintenance

beat:
	$(PY) -m celery -A app.celery_app beat -l info

# Run them as containers instead, to exercise the production image.
workers-docker:
	docker compose --profile workers up -d --build

# dbt: credentials come from .env via the runner, so these mirror `make` usage.
DBT := DBT_PROFILES_DIR=$(CURDIR)/dbt $(CURDIR)/.venv/Scripts/dbt.exe

dbt-deps:
	cd dbt && $(DBT) deps

dbt-build:
	cd dbt && $(DBT) build

dbt-test:
	cd dbt && $(DBT) test

dbt-docs:
	cd dbt && $(DBT) docs generate && $(DBT) docs serve

api:
	$(PY) -m uvicorn app.api.main:app --reload --port 8000

forecast:
	$(PY) -c "from app.core.db import session_scope; from app.forecasting.train import train_and_forecast; 	          import warnings; warnings.filterwarnings('ignore'); 	          s=session_scope().__enter__(); print(train_and_forecast(s).as_dict())"

alerts:
	$(PY) -c "from app.alerting.service import run_alert_cycle; print(run_alert_cycle())"

# Opt-in BI. Metabase is a JVM (~1GB) -- not part of the default stack.
metabase:
	docker compose --profile bi up -d metabase

review:
	$(PY) -m streamlit run app/ui/review.py

match:
	$(PY) -c "import warnings; warnings.filterwarnings('ignore'); 	          from app.core.db import session_scope; 	          from app.ai.matching import embed_pending_products, generate_matches; 	          s=session_scope().__enter__(); print(embed_pending_products(s).as_dict()); print(generate_matches(s).as_dict())"

brief:
	$(PY) -c "import warnings; warnings.filterwarnings('ignore'); 	          from app.core.db import session_scope; from app.ai.brief import generate_brief; 	          s=session_scope().__enter__(); print(generate_brief(s).body)"

flower:
	$(PY) -m celery -A app.celery_app flower --port=5555 --broker=redis://localhost:6379/0

logs:
	docker compose logs -f db redis
