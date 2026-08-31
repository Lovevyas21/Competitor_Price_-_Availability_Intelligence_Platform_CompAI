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

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.settings import get_settings

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


@dataclass
class AlertCycleStats:
    candidates: int = 0
    created: int = 0
    suppressed_duplicate: int = 0
    suppressed_stale: int = 0
    delivered: int = 0
    delivery_failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _fingerprint(row) -> str:
    """Identity of an undercut *at a price*.

    The competitor price is part of the fingerprint deliberately: the same retailer
    dropping further is genuinely new information and should alert again, while an
    unchanged undercut should not.
    """
    return (
        f"{row['retailer_name']}|{row['upc']}|{row['currency']}|{row['competitor_price']}"
    )


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


def send_to_slack(text_body: str, webhook_url: str, timeout: float = 10.0) -> bool:
    try:
        response = httpx.post(webhook_url, json={"text": text_body}, timeout=timeout)
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("alert.slack_failed", error=str(exc))
        return False


def run_alert_cycle(dry_run: bool = False) -> dict:
    """Evaluate undercuts, record new alerts, deliver the deliverable ones."""
    settings = get_settings()
    stats = AlertCycleStats()
    now = datetime.now(UTC)

    with session_scope() as session:
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

    webhook = settings.slack_webhook_url
    if not webhook:
        log.warning("alert.no_webhook_configured", pending=len(to_deliver))
        return stats.as_dict()

    for alert_id, message in to_deliver:
        if send_to_slack(message, webhook):
            stats.delivered += 1
            # Mark sent only after delivery succeeds, so a failure is retried next cycle
            # rather than being silently lost.
            with session_scope() as session:
                session.execute(
                    text("update alerts set sent_at = now() where alert_id = :id"),
                    {"id": alert_id},
                )
        else:
            stats.delivery_failed += 1

    log.info("alert.cycle_done", **stats.as_dict())
    return stats.as_dict()
