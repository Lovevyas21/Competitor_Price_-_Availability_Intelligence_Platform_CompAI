PY := .venv/Scripts/python.exe

.PHONY: install up down migrate lint test fmt reset worker beat workers-docker flower logs

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

flower:
	$(PY) -m celery -A app.celery_app flower --port=5555 --broker=redis://localhost:6379/0

logs:
	docker compose logs -f db redis
