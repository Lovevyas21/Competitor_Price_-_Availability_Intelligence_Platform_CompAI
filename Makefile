PY := .venv/Scripts/python.exe

.PHONY: install up down migrate lint test fmt reset

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
