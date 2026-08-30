# ADR-005: Celery Beat for scheduling, not Airflow/Dagster

**Status:** Accepted

## Context
The workload is periodic polling of public APIs with fan-out to per-SKU fetches. The
obvious alternatives are a full orchestrator (Airflow, Dagster, Prefect) or Celery with
Beat.

An orchestrator earns its weight when you need DAG lineage, asset-aware scheduling,
managed backfills across interdependent jobs, and a UI for reasoning about task
dependencies. None of that is true here yet: the dependency graph is one level deep
(schedule -> fan-out -> fetch), and backfill is a parameter on a task, not a DAG rerun.
Airflow would also add a scheduler, webserver, and its own metadata database -- material
cost on a machine already RAM-constrained.

## Decision
Celery 5.5 with Beat, Redis as broker and result backend.

- **Queues:** `ingest` (API-bound work), `default` (scheduling/fan-out), `maintenance`.
  Separating them means a long ingest backlog cannot starve partition maintenance.
- **At-least-once delivery:** `task_acks_late=True` plus `task_reject_on_worker_lost`.
  A crashed worker re-runs its task rather than losing it. This is only safe because
  every event carries an idempotency key -- duplicates collapse in the database.
- **`worker_prefetch_multiplier=1`:** tasks are long and I/O-bound, so hoarding messages
  just delays work an idle worker could take.
- **Rate limiting in Redis, not Celery.** Celery's `rate_limit` is per-worker, so running
  three workers silently triples the request rate at the upstream API. A shared token
  bucket in Redis holds the limit regardless of worker count. A separate daily-quota
  counter covers APIs that bill per day (eBay's documented 5,000/day default).
- **Dead-letter store:** payloads that exhaust retries are written to a store with the
  same layout and backends as bronze, so they can be inspected and replayed with the
  same tooling.
- **Flower runs from the local venv, not as a container** (`make flower`), installed via
  an optional `monitoring` extra. It is a debugging tool used occasionally; a dedicated
  container would hold memory permanently on a RAM-constrained machine. This also avoids
  shipping the monitoring UI in the deployed worker image.
- **Backfill by replay:** `replay_from_bronze(source, day)` re-parses stored raw payloads
  and re-applies them. Fixing a normalizer bug costs no upstream traffic and no quota,
  and idempotency keys make repeated replays safe.

## Consequences
- Cheap to run and to reason about; no orchestrator infrastructure.
- No DAG lineage or asset-level observability. When forecasting, dbt, and alerting become
  interdependent with real backfill requirements, this is the boundary to revisit --
  Dagster is the likely successor because its asset model fits a warehouse better than
  Airflow's task model.
- Retry policy is per-task code rather than declarative config, so it must be reviewed
  when adding a source.
- Flower cannot be used if the broker is ever switched to SQS; that trade-off is
  recorded in ADR-003.
