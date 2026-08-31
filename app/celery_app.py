"""Celery application: broker config, queues, and Beat schedules.

Why Celery Beat rather than Airflow/Dagster: this workload is periodic API polling with
task fan-out, which Beat handles with far less operational weight. The trade-off is no
DAG lineage, no asset-aware backfills, and no managed retry UI -- the point at which an
orchestrator earns its keep. See ADR-005.

Delivery semantics are deliberately **at-least-once**: `acks_late=True` means a task is
acknowledged only after it completes, so a worker crash re-runs the task rather than
losing it. Duplicate work is safe because every event carries an idempotency key.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

from app.core.logging import configure_logging
from app.core.settings import get_settings

settings = get_settings()

app = Celery("cpi", broker=settings.redis_url, backend=settings.redis_url)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # At-least-once delivery. Safe here because ingestion is idempotent.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Small prefetch: these tasks are long and I/O-bound, so hoarding messages just
    # delays work that an idle worker could pick up.
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,
    task_track_started=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    result_expires=86_400,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    task_routes={
        "app.ingestion.tasks.fetch_sku": {"queue": "ingest"},
        "app.ingestion.tasks.ingest_source_task": {"queue": "ingest"},
        "app.ingestion.tasks.ingest_seeds_task": {"queue": "ingest"},
        "app.ingestion.tasks.enqueue_tier": {"queue": "default"},
        "app.ingestion.tasks.ensure_future_partitions": {"queue": "maintenance"},
        "app.ingestion.tasks.build_marts": {"queue": "maintenance"},
    },
)

app.autodiscover_tasks(["app.ingestion"])


@setup_logging.connect
def _configure_celery_logging(**_kwargs):
    """Use structlog for worker logs instead of Celery's default formatter."""
    configure_logging(settings.log_level, pretty=settings.env == "dev")


app.conf.beat_schedule = {
    # Tier-1 SKUs: high-volatility, refreshed every 6 hours.
    "tier1-every-6h": {
        "task": "app.ingestion.tasks.enqueue_tier",
        "schedule": crontab(minute=0, hour="*/6"),
        "args": (1,),
    },
    # Tier-2: daily, off-peak.
    "tier2-daily": {
        "task": "app.ingestion.tasks.enqueue_tier",
        "schedule": crontab(minute=30, hour=2),
        "args": (2,),
    },
    # Tier-3: weekly.
    "tier3-weekly": {
        "task": "app.ingestion.tasks.enqueue_tier",
        "schedule": crontab(minute=0, hour=4, day_of_week=0),
        "args": (3,),
    },
    # Broad discovery sweep -- cheap, keeps catalogue coverage growing.
    "discover-daily": {
        "task": "app.ingestion.tasks.ingest_source_task",
        "schedule": crontab(minute=15, hour=1),
        "args": ("openprices", 300),
    },
    # Rebuild marts after the daily sweep has landed. Downstream consumers -- the API,
    # the dashboard and the nightly forecast -- all read marts, so they are refreshed
    # before any of those run.
    "marts-daily": {
        "task": "app.ingestion.tasks.build_marts",
        "schedule": crontab(minute=45, hour=1),
    },
    # Create next month's partitions well before they are needed. Without this,
    # the first write after a month boundary fails with "no partition found".
    "partitions-monthly": {
        "task": "app.ingestion.tasks.ensure_future_partitions",
        "schedule": crontab(minute=0, hour=0, day_of_month=25),
        "args": (3,),
    },
}
