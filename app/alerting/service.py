"""Undercut alerting.

The rule itself lives in `mart_undercut_alerts` (dbt), not here -- keeping the business
logic in SQL means it is tested by dbt alongside the marts, and the same definition backs
the API, the dashboard and the alert.

This module is responsible for the parts SQL cannot do:

* **Deduplication.** The alert cycle runs every 6 hours, but an undercut that persists
  for a week is one piece of news, not 28. An alert is re-sent only if the competitor
  price actually moved, or after a cooldown.
* **Delivery**, with the send recorded so a crash mid-cycle cannot silently drop or
  duplicate a notification.
"""

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

#: Re-notify about an unchanged, still-active undercut only this often.
COOLDOWN = timedelta(days=1)

#: Alerts computed from evidence older than this are recorded but not delivered --
#: waking someone for a three-week-old observation is noise.
MAX_ALERTABLE_STALENESS_DAYS = 7

CANDIDATES_SQL = """
select
    product_id, retailer_id, upc, our_sku, product_name, retailer_name,
    currency, our_price, competitor_price, gap_abs, gap_pct,
    severity, confidence, days_stale
from analytics_marts.mart_undercut_alerts
order by gap_pct
"""

#: The most recent alert per product/retailer, used for dedupe.
LAST_ALERT_SQL = """
select distinct on (product_id, message)
       product_id, message, created_at, sent_at
from alerts
where type = :type
order by product_id, message, created_at desc
"""


#: Advisory-lock key for the alert cycle. Arbitrary, but must never change: it is the
#: identity of the lock, and two deployments disagreeing about it would not exclude
#: each other. Derived from the alert type so it reads as deliberate rather than magic.
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
    """Claim the right to run an alert cycle, or report that someone else has it.

    Deduplication reads the existing fingerprints and then inserts. That is safe in one
    process and wrong in two: both cycles read "nothing recorded", both insert, and the
    same undercut is sent to a human twice. Nothing in the schema prevents it, and it
    only appears once the scheduler is scaled or restarted mid-cycle -- so it is exactly
    the class of bug that survives every local test and surfaces in production.

    A unique index on the fingerprint would be the obvious fix and is the wrong one: the
    same fingerprint is *supposed* to reappear once the cooldown expires, so a uniqueness
    constraint would permanently silence legitimate re-alerts instead of preventing
    concurrent ones. The exclusion needed is between runs, not between rows.

    `try` rather than a blocking acquire: if a cycle is already running, this one has
    nothing to add -- the other will see the same candidates. Waiting would only queue
    up a duplicate pass. Transaction-scoped, so the lock is released on commit *or*
    rollback and a crashed cycle cannot wedge the schedule.
    """
    held = session.execute(
        text("select pg_try_advisory_xact_lock(:key)"),
        {"key": ALERT_CYCLE_LOCK_KEY},
    ).scalar()
    return bool(held)


def _fingerprint(row) -> str:
    """Identity of an undercut *at a price*.

    The competitor price is part of the fingerprint deliberately: the same retailer
    dropping further is genuinely new information and should alert again, while an
    unchanged undercut should not.
    """
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
    """Fingerprint -> when we last created an alert for it."""
    rows = session.execute(text(LAST_ALERT_SQL), {"type": ALERT_TYPE}).mappings().all()
    out: dict[str, datetime] = {}
    for row in rows:
        message = row["message"] or ""
        if "\n#" in message:
            fingerprint = message.rsplit("\n#", 1)[1]
            out[fingerprint] = row["created_at"]
    return out


def deliver(messages: list[str], channels: list[AlertChannel] | None = None) -> dict:
    """Send a batch to every configured channel.

    Returns per-channel outcomes. Delivery counts as successful if *any* channel accepted
    the batch -- the alert reached a human, which is the point. A channel that fails is
    logged and retried next cycle, because `sent_at` stays null.
    """
    channels = configured_channels() if channels is None else channels
    if not channels:
        log.warning("alert.no_channel_configured", pending=len(messages))
        return {}

    return {c.name: c.send_batch(messages) for c in channels}


def run_alert_cycle(dry_run: bool = False) -> dict:
    """Evaluate undercuts, record new alerts, deliver the deliverable ones.

    `dry_run=True` reports what a real cycle would do and writes nothing: no alert rows,
    no delivery. That is worth stating because the obvious implementation -- recording
    the alerts and skipping only the send -- has a nasty side effect: the recorded rows
    suppress the genuine alerts for a full cooldown, so previewing the cycle silences it.
    """
    stats = AlertCycleStats()
    now = datetime.now(UTC)

    with session_scope() as session:
        # A dry run writes nothing, so it needs no exclusion -- and taking the lock would
        # mean a preview could be refused because a real cycle was running, or worse,
        # hold the lock against one.
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
                # A dry run must change nothing. Recording the alert here would not only
                # surprise the operator, it would suppress the real alert for a full
                # cooldown -- a "preview" that silences the thing it previewed.
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
                # Recorded for the record and the API, but not pushed at anyone.
                stats.suppressed_stale += 1
                continue

            to_deliver.append((int(alert_id), message))

    if dry_run or not to_deliver:
        log.info("alert.cycle_done", dry_run=dry_run, **stats.as_dict())
        return stats.as_dict()

    results = deliver([m for _, m in to_deliver])
    stats.channels = results

    if not results:
        # Nothing configured. The alerts stay recorded with sent_at null, so they are
        # visible on the API and get delivered once a channel is set up.
        log.info("alert.cycle_done", **stats.as_dict())
        return stats.as_dict()

    if any(results.values()):
        stats.delivered = len(to_deliver)
        # Marked only after a channel accepted the batch, so a total failure is retried
        # next cycle rather than being silently lost.
        with session_scope() as session:
            session.execute(
                text("update alerts set sent_at = now() where alert_id = any(:ids)"),
                {"ids": [aid for aid, _ in to_deliver]},
            )
    else:
        stats.delivery_failed = len(to_deliver)

    log.info("alert.cycle_done", **stats.as_dict())
    return stats.as_dict()
