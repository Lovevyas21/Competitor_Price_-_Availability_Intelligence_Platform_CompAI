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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
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
        "app.ingestion.tasks.train_forecasts": {"queue": "maintenance"},
        "app.ingestion.tasks.refresh_matches": {"queue": "maintenance"},
        "app.ingestion.tasks.generate_brief": {"queue": "maintenance"},
        "app.ingestion.tasks.evaluate_alerts": {"queue": "default"},
    },
)

app.autodiscover_tasks(["app.ingestion"])


@setup_logging.connect
def _configure_celery_logging(**_kwargs):
    configure_logging(settings.log_level, pretty=settings.env == "dev")


app.conf.beat_schedule = {
    "tier1-every-6h": {
        "task": "app.ingestion.tasks.enqueue_tier",
        "schedule": crontab(minute=0, hour="*/6"),
        "args": (1,),
    },
    "tier2-daily": {
        "task": "app.ingestion.tasks.enqueue_tier",
        "schedule": crontab(minute=30, hour=2),
        "args": (2,),
    },
    "tier3-weekly": {
        "task": "app.ingestion.tasks.enqueue_tier",
        "schedule": crontab(minute=0, hour=4, day_of_week=0),
        "args": (3,),
    },
    "discover-daily": {
        "task": "app.ingestion.tasks.ingest_source_task",
        "schedule": crontab(minute=15, hour=1),
        "args": ("openprices", 300),
    },
    "marts-daily": {
        "task": "app.ingestion.tasks.build_marts",
        "schedule": crontab(minute=45, hour=1),
    },
    "nightly-train": {
        "task": "app.ingestion.tasks.train_forecasts",
        "schedule": crontab(minute=0, hour=3),
    },
    "alerts-every-6h": {
        "task": "app.ingestion.tasks.evaluate_alerts",
        "schedule": crontab(minute=20, hour="*/6"),
    },
    "matches-daily": {
        "task": "app.ingestion.tasks.refresh_matches",
        "schedule": crontab(minute=15, hour=2),
    },
    "weekly-brief": {
        "task": "app.ingestion.tasks.generate_brief",
        "schedule": crontab(minute=0, hour=6, day_of_week=1),
    },
    "partitions-monthly": {
        "task": "app.ingestion.tasks.ensure_future_partitions",
        "schedule": crontab(minute=0, hour=0, day_of_month=25),
        "args": (3,),
    },
}
