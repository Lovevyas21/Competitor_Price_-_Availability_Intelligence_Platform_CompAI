FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

COPY pyproject.toml README.md ./
COPY app/__init__.py app/__init__.py
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python ".[transform,aws,ai]"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 cpi

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY dbt/ ./dbt/
COPY alembic.ini ./

RUN mkdir -p /app/data/bronze /app/data/deadletter && chown -R cpi:cpi /app
USER cpi

CMD ["celery", "-A", "app.celery_app", "worker", "-l", "info"]
