# Multi-stage build: dependencies resolve once in the builder, the runtime image carries
# only the virtualenv and application code.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Copy only what the dependency resolution needs, so edits to app code do not bust the
# layer cache and force a full reinstall.
COPY pyproject.toml README.md ./
COPY app/__init__.py app/__init__.py
# Extras, not a bare `.`. Each covers something only the deployed host does, and each
# is imported lazily, so omitting it fails in production and nowhere else:
#   transform  rebuilds marts after an ingest (dbt)
#   aws        stores raw payloads in S3, sends SES mail (boto3)
#   ai         narrates the weekly brief and answers chat (crewai, google-genai)
# Without `ai` the brief silently falls back to its deterministic renderer, which
# looks like a working feature rather than a missing dependency.
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python ".[transform,aws,ai]"


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as a non-root user: the worker holds API credentials and DB access.
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
