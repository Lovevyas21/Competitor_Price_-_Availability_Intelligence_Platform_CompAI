"""The bulk CDC path must be indistinguishable from the row-by-row one.

`bulk.apply_records_bulk` exists purely for speed over a high-latency link. If it ever
diverges from `cdc.apply_record`, history silently becomes wrong -- which is the one
failure this project cannot tolerate. So both paths are run over identical input and the
resulting rows are compared.

Each path runs inside a transaction that is rolled back, so the test leaves no trace in
whichever database is configured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.ingestion.bulk import apply_records_bulk
from app.ingestion.cdc import CDCStats, apply_record, get_or_create_source
from app.models.domain import (
    NormalizedRecord,
    PriceObservation,
    ProductAttributes,
    ProductIdentity,
)

SOURCE = "cdc-parity-test"
BASE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def require_database():
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("database not reachable")


def record(external_id: str, price: str, day: int, retailer: str, title: str = "Thing"):
    return NormalizedRecord(
        identity=ProductIdentity(source=SOURCE, external_id=external_id, tier=1),
        attributes=ProductAttributes(title=title, brand="B", category="C"),
        price=PriceObservation(
            price=Decimal(price), currency="EUR", observed_at=BASE + timedelta(days=day)
        ),
        retailer_name=retailer,
    )


#: Deliberately exercises the tricky cases: an unchanged price inside the heartbeat, a
#: genuine change, an unchanged price beyond the heartbeat, two retailers for one
#: product on the same day, and out-of-order (backfilled) arrival.
DATASET = [
    record("A", "1.00", 0, "Shop1"),
    record("A", "1.00", 0, "Shop2"),          # same day, different retailer
    record("A", "1.00", 1, "Shop1"),          # unchanged, beyond 24h heartbeat
    record("A", "2.00", 2, "Shop1"),          # genuine change
    record("A", "2.00", 2, "Shop1"),          # exact duplicate
    record("B", "5.50", 5, "Shop1"),
    record("B", "5.50", 3, "Shop1"),          # arrives late, predates the row above
    record("B", "6.00", 4, "Shop1"),          # slots between them in time
]

SNAPSHOT_SQL = """
select p.external_id, r.name as retailer, pe.price, pe.observed_at
from price_events pe
join products p on p.product_id = pe.product_id
left join retailers r on r.retailer_id = pe.retailer_id
where p.source_id = :sid
order by p.external_id, r.name nulls first, pe.observed_at
"""

VERSION_SQL = """
select p.external_id, pv.title, pv.is_current
from product_versions pv
join products p on p.product_id = pv.product_id
where p.source_id = :sid
order by p.external_id, pv.version_id
"""


def _run(apply_fn) -> tuple[list, list]:
    """Apply the dataset with one strategy, snapshot the result, then roll back."""
    session = SessionLocal()
    try:
        session.begin()
        sid = get_or_create_source(session, SOURCE, "http://test", "none")
        apply_fn(session, sid)
        events = [tuple(r) for r in session.execute(text(SNAPSHOT_SQL), {"sid": sid})]
        versions = [tuple(r) for r in session.execute(text(VERSION_SQL), {"sid": sid})]
        return events, versions
    finally:
        session.rollback()
        session.close()


def _rowwise(session, sid):
    stats = CDCStats()
    # The row-by-row path relies on the caller ordering history chronologically.
    for rec in sorted(DATASET, key=lambda r: r.observed_at):
        apply_record(session, sid, rec, stats)


def _bulk(session, sid):
    apply_records_bulk(session, sid, DATASET)


def test_price_events_are_identical():
    rowwise_events, _ = _run(_rowwise)
    bulk_events, _ = _run(_bulk)
    assert bulk_events == rowwise_events


def test_product_versions_are_identical():
    _, rowwise_versions = _run(_rowwise)
    _, bulk_versions = _run(_bulk)
    assert bulk_versions == rowwise_versions


def test_both_paths_collapse_the_exact_duplicate():
    """The dataset contains one exact duplicate; neither path may record it twice."""
    bulk_events, _ = _run(_bulk)
    assert len(bulk_events) == len(set(bulk_events))


def test_both_paths_keep_one_current_version_per_product():
    _, versions = _run(_bulk)
    current = [v for v in versions if v[2]]
    assert len(current) == len({v[0] for v in versions})
