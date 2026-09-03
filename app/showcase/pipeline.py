"""The five stages the showcase walks through, and the real work behind each one.

Every number this module emits is read from the warehouse at the moment you press run.
Nothing here is scripted, cached or seeded for the demo -- if the database is empty the
console says so, at length, rather than performing a success.

That distinction matters enough to be a design rule: **the pacing is theatre, the data is
not.** Stages are timed with a real clock and reported in real milliseconds. The
line-by-line reveal that makes it look cinematic happens in the browser, after the
numbers have already arrived (see `static/showcase.js`). The server never sleeps to look
busy. A stage that renders slowly is a stage the browser is still typing out; a stage
that *reports* 900 ms genuinely took 900 ms.

Each stage is a generator of events. Yielding rather than returning is what lets the
console fill progressively instead of appearing all at once.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.alerting.channels import configured_channels
from app.core.db import session_scope
from app.core.settings import get_settings

Event = dict[str, Any]


# --------------------------------------------------------------------------- #
# event helpers
# --------------------------------------------------------------------------- #
def line(text_: str, cls: str = "") -> Event:
    return {"t": "line", "text": text_, "cls": cls}


def metric(label: str, value: Any, note: str = "", cls: str = "") -> Event:
    return {"t": "metric", "label": label, "value": str(value), "note": note, "cls": cls}


def table(cols: list[str], rows: list[list[Any]], caption: str = "") -> Event:
    return {
        "t": "table",
        "cols": cols,
        "rows": [[("" if c is None else str(c)) for c in r] for r in rows],
        "caption": caption,
    }


def _rows(session: Session, sql: str, **params) -> list[dict]:
    return [dict(r) for r in session.execute(text(sql), params).mappings()]


def _scalar(session: Session, sql: str, **params) -> Any:
    return session.execute(text(sql), params).scalar()


# --------------------------------------------------------------------------- #
# stage 1 -- connect
# --------------------------------------------------------------------------- #
def stage_connect(session: Session) -> Iterator[Event]:
    """Prove the warehouse is actually there before claiming anything about it."""
    yield line("opening connection to the warehouse", "dim")

    version = _scalar(session, "select version()") or ""
    yield line(version.split(" on ")[0], "ok")

    settings = get_settings()
    yield metric(
        "Database", f"{settings.postgres_db}@{settings.postgres_host}:{settings.postgres_port}"
    )

    sources = _rows(
        session,
        "select name, base_url, auth_type from sources order by source_id",
    )
    yield metric("Sources registered", len(sources))
    if sources:
        yield table(
            ["source", "endpoint", "auth"],
            [[s["name"], s["base_url"], s["auth_type"] or "none"] for s in sources],
        )

    bronze = Path(settings.bronze_local_path)
    payloads = sum(1 for _ in bronze.rglob("*")) if bronze.exists() else 0
    yield metric(
        "Raw payloads on disk",
        f"{payloads:,}",
        "bronze layer -- every response kept before parsing, so the warehouse "
        "can be rebuilt without re-calling anyone",
    )

    partitions = _scalar(
        session,
        """
        select count(*) from pg_inherits i
        join pg_class parent on parent.oid = i.inhparent
        where parent.relname = 'price_events'
        """,
    )
    yield metric("Monthly partitions", partitions, "created on demand as observations arrive")


# --------------------------------------------------------------------------- #
# stage 2 -- extract
# --------------------------------------------------------------------------- #
def stage_extract(session: Session) -> Iterator[Event]:
    """What actually landed: the observations, and who they came from."""
    yield line("reading normalised observations", "dim")

    counts = _rows(
        session,
        """
        select
          (select count(*) from price_events)              as events,
          (select count(*) from products)                  as products,
          (select count(*) from retailers)                 as retailers,
          (select count(distinct currency) from price_events) as currencies,
          (select min(observed_at)::date from price_events)   as first_seen,
          (select max(observed_at)::date from price_events)   as last_seen
        """,
    )[0]

    if not counts["events"]:
        yield line("no price events in the warehouse -- run an ingest first", "err")
        yield line("make ingest   (or: python -m app.cli ingest --days 90)", "dim")
        return

    yield metric("Price observations", f"{counts['events']:,}")
    yield metric("Products tracked", f"{counts['products']:,}")
    yield metric("Retailers", f"{counts['retailers']:,}")
    yield metric(
        "Currencies",
        counts["currencies"],
        "currency is part of the grain everywhere -- prices are never compared across it",
    )
    yield metric("History span", f"{counts['first_seen']} to {counts['last_seen']}")

    yield line("sampling the most recent observations", "dim")
    recent = _rows(
        session,
        """
        select r.name as retailer,
               coalesce(pv.title, p.external_id) as product,
               pe.price, pe.currency, pe.observed_at::date as seen
        from price_events pe
        join products  p using (product_id)
        join retailers r using (retailer_id)
        left join product_versions pv
               on pv.product_id = p.product_id and pv.is_current
        order by pe.observed_at desc
        limit 8
        """,
    )
    yield table(
        ["retailer", "product", "price", "ccy", "observed"],
        [[r["retailer"], r["product"], r["price"], r["currency"], r["seen"]] for r in recent],
        "live rows from price_events",
    )

    yield line(
        "stored insert-on-change: a price that has not moved is not a new row, "
        "but a 24h heartbeat still records that we looked",
        "dim",
    )


# --------------------------------------------------------------------------- #
# stage 3 -- resolve
# --------------------------------------------------------------------------- #
def stage_resolve(session: Session) -> Iterator[Event]:
    """Deciding which of their products are our products."""
    yield line("resolving competitor listings against our catalogue", "dim")
    yield line(
        "retailers do not share our SKUs, so identity is inferred: "
        "exact barcode first, then embedding similarity on the title",
        "dim",
    )

    bands = _rows(
        session,
        """
        select status, method, count(*) as n,
               round(min(confidence), 3) as lo,
               round(max(confidence), 3) as hi
        from product_matches
        group by status, method
        order by status, method
        """,
    )
    if not bands:
        yield line("no candidate matches yet -- run the matcher", "warn")
        return

    yield table(
        ["status", "method", "pairs", "min conf", "max conf"],
        [[b["status"], b["method"], f"{b['n']:,}", b["lo"], b["hi"]] for b in bands],
    )

    auto = sum(b["n"] for b in bands if b["status"] == "approved")
    pending = sum(b["n"] for b in bands if b["status"] == "pending")
    yield metric("Auto-matched", f"{auto:,}", "similarity >= 0.92, accepted without a human")
    yield metric(
        "Queued for review",
        f"{pending:,}",
        "0.80-0.92 -- a suggestion, not a decision; a person confirms these",
        cls="warn",
    )
    yield line(
        "the middle band is deliberate. Auto-approving it would inflate coverage "
        "and quietly corrupt every price comparison downstream",
        "dim",
    )

    sample = _rows(
        session,
        """
        select round(m.confidence, 4) as confidence,
               coalesce(va.title, a.external_id) as ours,
               coalesce(vb.title, b.external_id) as theirs
        from product_matches m
        join products a on a.product_id = m.product_id_a
        join products b on b.product_id = m.product_id_b
        left join product_versions va on va.product_id = a.product_id and va.is_current
        left join product_versions vb on vb.product_id = b.product_id and vb.is_current
        where m.status = 'approved'
        order by m.confidence desc
        limit 6
        """,
    )
    if sample:
        yield table(
            ["confidence", "our listing", "their listing"],
            [[s["confidence"], s["ours"], s["theirs"]] for s in sample],
            "highest-confidence automatic matches",
        )


# --------------------------------------------------------------------------- #
# stage 4 -- compare
# --------------------------------------------------------------------------- #
def stage_compare(session: Session) -> Iterator[Event]:
    """Where the money question gets answered: who is cheaper than us, and by how much."""
    yield line("comparing matched pairs against our own catalogue", "dim")

    gaps = _scalar(session, "select count(*) from analytics_marts.mart_price_gap_vs_own")
    if not gaps:
        yield line("price gap mart is empty -- rebuild the marts (make dbt-build)", "err")
        return

    yield metric("Comparable pairs", f"{gaps:,}", "same product, same currency, both sides priced")

    undercuts = _rows(
        session,
        """
        select severity, count(*) as n
        from analytics_marts.mart_undercut_alerts
        group by severity
        order by case severity when 'critical' then 1 when 'high' then 2 else 3 end
        """,
    )
    total = sum(u["n"] for u in undercuts)
    yield metric("Undercuts detected", f"{total:,}", cls="warn" if total else "")
    if undercuts:
        yield table(
            ["severity", "count"],
            [[u["severity"], f"{u['n']:,}"] for u in undercuts],
        )

    yield line("ranking by gap", "dim")
    top = _rows(
        session,
        """
        select product_name, retailer_name, currency,
               our_price, competitor_price, round(gap_pct, 2) as gap_pct,
               severity, days_stale
        from analytics_marts.mart_undercut_alerts
        order by gap_pct
        limit 8
        """,
    )
    yield table(
        ["product", "retailer", "ours", "theirs", "gap %", "severity", "days old"],
        [
            [
                t["product_name"],
                t["retailer_name"],
                f"{t['our_price']} {t['currency']}",
                f"{t['competitor_price']} {t['currency']}",
                t["gap_pct"],
                t["severity"],
                t["days_stale"],
            ]
            for t in top
        ],
        "steepest undercuts, worst first",
    )


# --------------------------------------------------------------------------- #
# stage 5 -- decide
# --------------------------------------------------------------------------- #
def stage_decide(session: Session) -> Iterator[Event]:
    """A detection is not yet an alert. This is the part that decides what to send."""
    yield line("applying the freshness gate", "dim")

    split = _rows(
        session,
        """
        select
          count(*) filter (where days_stale <= 7) as deliverable,
          count(*) filter (where days_stale >  7) as withheld,
          count(*)                                as total
        from analytics_marts.mart_undercut_alerts
        """,
    )[0]

    yield metric("Fresh enough to send", split["deliverable"], "evidence 7 days old or less")
    yield metric(
        "Recorded but withheld",
        split["withheld"],
        "waking someone for a three-week-old observation is noise, so it is kept and not sent",
        cls="dim",
    )

    alerts = _rows(
        session,
        """
        select count(*) as recorded,
               count(*) filter (where sent_at is not null) as delivered
        from alerts where type = 'undercut'
        """,
    )[0]
    yield metric("Alerts on record", f"{alerts['recorded']:,}")
    yield metric("Marked delivered", f"{alerts['delivered']:,}")

    channels = [c.name for c in configured_channels()]
    if channels:
        yield metric("Delivery channels live", ", ".join(channels), cls="ok")
    else:
        yield metric(
            "Delivery channels live",
            "none configured",
            "nothing sends until a webhook, SMTP host or SES region is set -- "
            "a fresh checkout cannot message anyone by accident",
            cls="warn",
        )

    yield line("an undercut that persists for a week is one piece of news, not twenty-eight", "dim")
    yield line("re-sent only if the competitor price actually moves, or after a cooldown", "dim")

    forecasts = _rows(
        session,
        """
        select count(distinct product_id) as series, count(*) as points,
               count(distinct model) as models
        from forecasts
        """,
    )[0]
    if forecasts["points"]:
        yield metric(
            "Forecast series",
            forecasts["series"],
            f"{forecasts['points']:,} points across {forecasts['models']} models, "
            "backtested on held-out days",
        )


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
STAGES: list[dict] = [
    {
        "id": "connect",
        "title": "Connect",
        "subtitle": "reach the warehouse and confirm what is registered",
        "fn": stage_connect,
    },
    {
        "id": "extract",
        "title": "Extract",
        "subtitle": "what was collected, from whom, in what currency",
        "fn": stage_extract,
    },
    {
        "id": "resolve",
        "title": "Resolve",
        "subtitle": "decide which of their products are our products",
        "fn": stage_resolve,
    },
    {
        "id": "compare",
        "title": "Compare",
        "subtitle": "find who is cheaper than us, and by how much",
        "fn": stage_compare,
    },
    {
        "id": "decide",
        "title": "Decide",
        "subtitle": "turn detections into alerts worth sending",
        "fn": stage_decide,
    },
]


def run_pipeline(only: str | None = None) -> Iterator[Event]:
    """Walk the stages, emitting events as each completes.

    One session for the whole run, so the console describes a single consistent
    snapshot rather than five that drifted apart while it was being rendered.

    A stage that raises does not kill the run: it reports the failure and the walk
    continues. A demo that dies halfway tells you less than one that says which part
    broke.
    """
    started = time.perf_counter()
    stages = [s for s in STAGES if only is None or s["id"] == only]

    try:
        with session_scope() as session:
            for stage in stages:
                yield {
                    "t": "stage",
                    "id": stage["id"],
                    "title": stage["title"],
                    "subtitle": stage["subtitle"],
                }
                begin = time.perf_counter()
                try:
                    yield from stage["fn"](session)
                except Exception as exc:  # noqa: BLE001 - a broken stage must not end the run
                    # The rollback is the load-bearing half. Postgres aborts the whole
                    # transaction on a failed statement, so without it a single bad query
                    # in stage one makes every later stage fail with "transaction is
                    # aborted" -- one real error wearing four fake ones as a disguise.
                    session.rollback()
                    yield line(f"{type(exc).__name__}: {str(exc).splitlines()[0]}", "err")
                yield {
                    "t": "stage_done",
                    "id": stage["id"],
                    "ms": round((time.perf_counter() - begin) * 1000),
                }
    except Exception as exc:  # noqa: BLE001 - most likely the database is simply down
        yield {
            "t": "stage",
            "id": "error",
            "title": "Unavailable",
            "subtitle": "the warehouse could not be reached",
        }
        yield line(f"{type(exc).__name__}: {exc}", "err")
        yield line("is the database up?  docker compose ps", "dim")
        yield {"t": "done", "ms": round((time.perf_counter() - started) * 1000), "ok": False}
        return

    yield {"t": "done", "ms": round((time.perf_counter() - started) * 1000), "ok": True}
