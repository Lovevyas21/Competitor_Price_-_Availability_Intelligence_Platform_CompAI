from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.alerting.channels import AlertChannel, configured_channels
from app.core.db import session_scope
from app.core.logging import get_logger

log = get_logger(__name__)

ALERT_TYPE = "undercut"

COOLDOWN = timedelta(days=1)

MAX_ALERTABLE_STALENESS_DAYS = 7

CANDIDATES_SQL = """
select
    product_id, retailer_id, upc, our_sku, product_name, retailer_name,
    currency, our_price, competitor_price, gap_abs, gap_pct,
    severity, confidence, days_stale
from analytics_marts.mart_undercut_alerts
order by gap_pct
"""

LAST_ALERT_SQL = """
select distinct on (product_id, message)
       product_id, message, created_at, sent_at
from alerts
where type = :type
order by product_id, message, created_at desc
"""


ALERT_CYCLE_LOCK_KEY = 0x_A1E7_C7C1


@dataclass
class AlertCycleStats:
    candidates: int = 0
    created: int = 0
    suppressed_duplicate: int = 0
    suppressed_stale: int = 0
    delivered: int = 0
    delivery_failed: int = 0
    skipped_locked: bool = False
    channels: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _acquire_cycle_lock(session: Session) -> bool:
    held = session.execute(
        text("select pg_try_advisory_xact_lock(:key)"),
        {"key": ALERT_CYCLE_LOCK_KEY},
    ).scalar()
    return bool(held)


def _fingerprint(row) -> str:
    return f"{row['retailer_name']}|{row['upc']}|{row['currency']}|{row['competitor_price']}"


def format_message(row) -> str:
    return (
        f"{row['retailer_name']} is undercutting {row['product_name']} "
        f"by {abs(float(row['gap_pct'])):.1f}% "
        f"({row['competitor_price']} vs {row['our_price']} {row['currency']}). "
        f"Observed {row['days_stale']}d ago."
    )


def load_candidates(session: Session) -> list[dict]:
    return [dict(r) for r in session.execute(text(CANDIDATES_SQL)).mappings().all()]


def existing_fingerprints(session: Session) -> dict[str, datetime]:
    rows = session.execute(text(LAST_ALERT_SQL), {"type": ALERT_TYPE}).mappings().all()
    out: dict[str, datetime] = {}
    for row in rows:
        message = row["message"] or ""
        if "\n#" in message:
            fingerprint = message.rsplit("\n#", 1)[1]
            out[fingerprint] = row["created_at"]
    return out


def deliver(messages: list[str], channels: list[AlertChannel] | None = None) -> dict:
    channels = configured_channels() if channels is None else channels
    if not channels:
        log.warning("alert.no_channel_configured", pending=len(messages))
        return {}

    return {c.name: c.send_batch(messages) for c in channels}


def run_alert_cycle(dry_run: bool = False) -> dict:
    stats = AlertCycleStats()
    now = datetime.now(UTC)

    with session_scope() as session:
        if not dry_run and not _acquire_cycle_lock(session):
            stats.skipped_locked = True
            log.info("alert.cycle_skipped", reason="another cycle holds the lock")
            return stats.as_dict()

        candidates = load_candidates(session)
        stats.candidates = len(candidates)
        seen = existing_fingerprints(session)

        to_deliver: list[tuple[int, str]] = []

        for row in candidates:
            fingerprint = _fingerprint(row)
            last_seen = seen.get(fingerprint)
            if last_seen is not None and (now - last_seen) < COOLDOWN:
                stats.suppressed_duplicate += 1
                continue

            message = format_message(row)
            stored = f"{message}\n#{fingerprint}"

            if dry_run:
                stats.created += 1
                if int(row["days_stale"]) > MAX_ALERTABLE_STALENESS_DAYS:
                    stats.suppressed_stale += 1
                continue

            alert_id = session.execute(
                text("""
                    insert into alerts (product_id, type, message, severity, created_at)
                    values (:pid, :type, :message, :severity, :created_at)
                    returning alert_id
                """),
                {
                    "pid": row["product_id"],
                    "type": ALERT_TYPE,
                    "message": stored,
                    "severity": row["severity"],
                    "created_at": now,
                },
            ).scalar_one()
            stats.created += 1

            if int(row["days_stale"]) > MAX_ALERTABLE_STALENESS_DAYS:
                stats.suppressed_stale += 1
                continue

            to_deliver.append((int(alert_id), message))

    if dry_run or not to_deliver:
        log.info("alert.cycle_done", dry_run=dry_run, **stats.as_dict())
        return stats.as_dict()

    results = deliver([m for _, m in to_deliver])
    stats.channels = results

    if not results:
        log.info("alert.cycle_done", **stats.as_dict())
        return stats.as_dict()

    if any(results.values()):
        stats.delivered = len(to_deliver)
        with session_scope() as session:
            session.execute(
                text("update alerts set sent_at = now() where alert_id = any(:ids)"),
                {"ids": [aid for aid, _ in to_deliver]},
            )
    else:
        stats.delivery_failed = len(to_deliver)

    log.info("alert.cycle_done", **stats.as_dict())
    return stats.as_dict()
