from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.base import SourceClient
from app.clients.registry import get_client
from app.core.db import session_scope
from app.core.logging import get_logger
from app.ingestion.bronze import BronzeStore, get_bronze_store
from app.ingestion.bulk import apply_records_bulk
from app.ingestion.cdc import CDCStats, get_or_create_source
from app.ingestion.idempotency import idempotency_key
from app.models.domain import NormalizedRecord
from app.models.validation import IngestionBatchFailed, validate_price_batch

log = get_logger(__name__)


@dataclass
class RunResult:
    source: str
    run_id: int | None
    fetched: int = 0
    normalized: int = 0
    skipped: int = 0
    status: str = "running"
    stats: CDCStats | None = None
    error: str | None = None

    def summary(self) -> dict:
        d = {
            "source": self.source,
            "run_id": self.run_id,
            "status": self.status,
            "fetched": self.fetched,
            "normalized": self.normalized,
            "skipped": self.skipped,
        }
        if self.stats:
            d |= self.stats.as_dict()
        if self.error:
            d["error"] = self.error
        return d


def _start_run(session: Session, source_id: int) -> int:
    return int(
        session.execute(
            text(
                "insert into ingestion_runs (source_id, status) "
                "values (:sid, 'running') returning run_id"
            ),
            {"sid": source_id},
        ).scalar_one()
    )


def _finish_run(
    session: Session, run_id: int, status: str, ok: int, failed: int, notes: str | None
) -> None:
    session.execute(
        text("""
            update ingestion_runs
            set finished_at = now(), status = :status,
                records_ok = :ok, records_failed = :failed, notes = :notes
            where run_id = :run_id
        """),
        {
            "run_id": run_id,
            "status": status,
            "ok": ok,
            "failed": failed,
            "notes": (notes[:2000] if notes else None),
        },
    )


def _persist_raw(
    store: BronzeStore, source: str, external_id: str, raw: object, observed_at: datetime
) -> None:
    key = idempotency_key(source, external_id, observed_at, kind="raw")
    store.put(source, observed_at, key, raw)


def ingest_source(
    source_name: str,
    limit: int = 100,
    *,
    client: SourceClient | None = None,
    store: BronzeStore | None = None,
) -> RunResult:
    client = client or get_client(source_name)
    store = store or get_bronze_store()
    result = RunResult(source=source_name, run_id=None)

    log.info("ingest.start", source=source_name, limit=limit)

    try:
        with session_scope() as session:
            source_id = get_or_create_source(
                session, client.name, client.base_url, client.auth_type
            )
            run_id = _start_run(session, source_id)
            result.run_id = run_id
    except Exception as exc:
        result.status = "failed"
        result.error = f"could not open run: {exc}"
        log.error("ingest.run_open_failed", source=source_name, error=str(exc))
        return result

    records: list[NormalizedRecord] = []
    fetch_started = datetime.now(UTC)

    try:
        for external_id, raw in client.discover(limit=limit):
            result.fetched += 1
            _persist_raw(store, client.name, external_id, raw, fetch_started)
            record = client.normalize(raw)
            if record is None:
                result.skipped += 1
                continue
            records.append(record)
        result.normalized = len(records)

        validate_price_batch(records, source=client.name)

        stats = CDCStats()
        with session_scope() as session:
            source_id = get_or_create_source(
                session, client.name, client.base_url, client.auth_type
            )
            stats = apply_records_bulk(session, source_id, records)
        result.stats = stats
        result.status = "success"

    except IngestionBatchFailed as exc:
        result.status = "failed"
        result.error = str(exc)
        log.error("ingest.validation_failed", source=source_name, error=str(exc))
    except Exception as exc:
        result.status = "failed"
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("ingest.failed", source=source_name)
    finally:
        client.close()
        ok = result.stats.price_events_inserted if result.stats else 0
        with session_scope() as session:
            _finish_run(session, result.run_id, result.status, ok, result.skipped, result.error)

    log.info("ingest.done", **result.summary())
    return result


def seed_from_source(source_name: str, limit: int = 50, tier: int = 1) -> list[tuple[str, int]]:
    client = get_client(source_name)
    try:
        candidates = client.top_external_ids(limit=limit)
    finally:
        client.close()

    if not candidates:
        log.warning("seed.unsupported", source=source_name)
        return []

    with session_scope() as session:
        for external_id, count, label in candidates:
            session.execute(
                text("""
                    insert into seed_products (source_name, external_id, tier, note)
                    values (:source, :external_id, :tier, :note)
                    on conflict (source_name, external_id) do update
                        set tier = excluded.tier, note = excluded.note, active = true
                """),
                {
                    "source": source_name,
                    "external_id": external_id,
                    "tier": tier,
                    "note": f"{count} observations upstream" + (f" ({label})" if label else ""),
                },
            )

    log.info("seed.done", source=source_name, seeded=len(candidates))
    return [(c[0], c[1]) for c in candidates]


def load_seed_ids(source_name: str, limit: int | None = None) -> list[str]:
    with session_scope() as session:
        rows = (
            session.execute(
                text("""
                select external_id from seed_products
                where source_name = :source and active
                order by tier, seed_id
                limit :limit
            """),
                {"source": source_name, "limit": limit or 1000},
            )
            .scalars()
            .all()
        )
    return list(rows)


def ingest_seeds(
    source_name: str,
    max_products: int = 25,
    *,
    client: SourceClient | None = None,
    store: BronzeStore | None = None,
) -> RunResult:
    client = client or get_client(source_name)
    store = store or get_bronze_store()
    result = RunResult(source=source_name, run_id=None)

    external_ids = load_seed_ids(source_name, limit=max_products)
    if not external_ids:
        result.status = "failed"
        result.error = f"no active seed_products for '{source_name}'; run `cpi seed` first"
        log.error("ingest_seeds.no_seeds", source=source_name)
        client.close()
        return result

    try:
        with session_scope() as session:
            source_id = get_or_create_source(
                session, client.name, client.base_url, client.auth_type
            )
            result.run_id = _start_run(session, source_id)
    except Exception as exc:
        result.status = "failed"
        result.error = f"could not open run: {exc}"
        client.close()
        return result

    records: list[NormalizedRecord] = []
    fetch_started = datetime.now(UTC)
    log.info("ingest_seeds.start", source=source_name, skus=len(external_ids))

    try:
        for external_id in external_ids:
            raw = client.fetch_raw(external_id)
            _persist_raw(store, client.name, external_id, raw, fetch_started)
            for row in client.iter_raw(raw):
                result.fetched += 1
                record = client.normalize(row)
                if record is None:
                    result.skipped += 1
                    continue
                records.append(record)
        result.normalized = len(records)

        validate_price_batch(records, source=client.name)

        stats = CDCStats()
        with session_scope() as session:
            source_id = get_or_create_source(
                session, client.name, client.base_url, client.auth_type
            )
            stats = apply_records_bulk(session, source_id, records)
        result.stats = stats
        result.status = "success"

    except IngestionBatchFailed as exc:
        result.status = "failed"
        result.error = str(exc)
        log.error("ingest_seeds.validation_failed", source=source_name, error=str(exc))
    except Exception as exc:
        result.status = "failed"
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("ingest_seeds.failed", source=source_name)
    finally:
        client.close()
        ok = result.stats.price_events_inserted if result.stats else 0
        with session_scope() as session:
            _finish_run(session, result.run_id, result.status, ok, result.skipped, result.error)

    log.info("ingest_seeds.done", **result.summary())
    return result
