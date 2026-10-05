from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.idempotency import idempotency_key
from app.models.domain import NormalizedRecord

log = get_logger(__name__)

HEARTBEAT = timedelta(hours=24)


@dataclass
class CDCStats:
    products_created: int = 0
    versions_opened: int = 0
    price_events_inserted: int = 0
    price_events_skipped_unchanged: int = 0
    price_events_duplicate: int = 0
    stock_events_inserted: int = 0
    partitions_created: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["partitions_created"] = sorted(d["partitions_created"])
        return d


def get_or_create_source(
    session: Session, name: str, base_url: str | None = None, auth_type: str = "none"
) -> int:
    row = session.execute(
        text("""
            insert into sources (name, base_url, auth_type)
            values (:name, :base_url, :auth_type)
            on conflict (name) do update set base_url = coalesce(
                excluded.base_url, sources.base_url)
            returning source_id
        """),
        {"name": name, "base_url": base_url, "auth_type": auth_type},
    ).scalar_one()
    return int(row)


def get_or_create_retailer(
    session: Session, source_id: int, name: str, country: str | None = None
) -> int:
    return int(
        session.execute(
            text("""
                insert into retailers (source_id, name, country)
                values (:source_id, :name, :country)
                on conflict (source_id, name) do update set country = coalesce(
                    excluded.country, retailers.country)
                returning retailer_id
            """),
            {"source_id": source_id, "name": name, "country": country},
        ).scalar_one()
    )


def ensure_partition(session: Session, parent: str, observed_at: datetime) -> str:
    month_start = observed_at.astimezone(UTC).date().replace(day=1)
    session.execute(
        text("select ensure_month_partition(:parent, :month_start)"),
        {"parent": parent, "month_start": month_start},
    )
    return f"{parent}_{month_start:%Y%m}"


def upsert_product(session: Session, source_id: int, record: NormalizedRecord) -> tuple[int, bool]:
    ident = record.identity
    result = session.execute(
        text("""
            insert into products (source_id, external_id, sku, upc, mpn, brand, category, tier)
            values (:source_id, :external_id, :sku, :upc, :mpn, :brand, :category, :tier)
            on conflict (source_id, external_id) do update set
                sku      = coalesce(excluded.sku, products.sku),
                upc      = coalesce(excluded.upc, products.upc),
                mpn      = coalesce(excluded.mpn, products.mpn),
                brand    = coalesce(excluded.brand, products.brand),
                category = coalesce(excluded.category, products.category),
                tier     = excluded.tier
            returning product_id, (xmax = 0) as created
        """),
        {
            "source_id": source_id,
            "external_id": ident.external_id,
            "sku": ident.sku,
            "upc": ident.upc,
            "mpn": ident.mpn,
            "brand": ident.brand,
            "category": ident.category,
            "tier": ident.tier,
        },
    ).one()
    return int(result.product_id), bool(result.created)


def apply_scd2_version(session: Session, product_id: int, record: NormalizedRecord) -> bool:
    attrs = record.attributes
    current = session.execute(
        text("""
            select version_id, title, brand, category
            from product_versions
            where product_id = :pid and is_current
        """),
        {"pid": product_id},
    ).one_or_none()

    incoming = attrs.scd2_fingerprint()
    if current is not None:
        existing = (current.title, current.brand, current.category)
        incoming = tuple(
            new if new is not None else old for new, old in zip(incoming, existing, strict=True)
        )
        if existing == incoming:
            return False
        session.execute(
            text("""
                update product_versions
                set is_current = false, valid_to = now()
                where version_id = :vid
            """),
            {"vid": current.version_id},
        )

    session.execute(
        text("""
            insert into product_versions
                (product_id, title, brand, category, attributes, valid_from, is_current)
            values (:pid, :title, :brand, :category, cast(:attributes as jsonb), now(), true)
        """),
        {
            "pid": product_id,
            "title": incoming[0],
            "brand": incoming[1],
            "category": incoming[2],
            "attributes": _json(attrs.attributes),
        },
    )
    return True


def _json(value: dict) -> str:
    import json

    return json.dumps(value, default=str)


def _preceding_price(
    session: Session, product_id: int, retailer_id: int | None, observed_at: datetime
):
    return session.execute(
        text("""
            select price, observed_at
            from price_events
            where product_id = :pid
              and retailer_id is not distinct from :rid
              and observed_at <= :observed_at
            order by observed_at desc
            limit 1
        """),
        {"pid": product_id, "rid": retailer_id, "observed_at": observed_at},
    ).one_or_none()


def record_price_event(
    session: Session,
    product_id: int,
    retailer_id: int | None,
    record: NormalizedRecord,
    stats: CDCStats,
) -> None:
    obs = record.price
    if obs is None:
        return

    stats.partitions_created.add(ensure_partition(session, "price_events", obs.observed_at))

    previous = _preceding_price(session, product_id, retailer_id, obs.observed_at)
    if previous is not None:
        unchanged = previous.price == obs.price
        within_heartbeat = obs.observed_at - previous.observed_at < HEARTBEAT
        if unchanged and within_heartbeat:
            stats.price_events_skipped_unchanged += 1
            return

    key = idempotency_key(
        source=record.identity.source,
        external_id=record.identity.external_id,
        observed_at=obs.observed_at,
        kind="price",
        discriminator=record.retailer_name,
    )
    inserted = session.execute(
        text("""
            insert into price_events
                (product_id, retailer_id, price, currency, observed_at, idempotency_key)
            values (:pid, :rid, :price, :currency, :observed_at, :key)
            on conflict (idempotency_key, observed_at) do nothing
            returning event_id
        """),
        {
            "pid": product_id,
            "rid": retailer_id,
            "price": obs.price,
            "currency": obs.currency,
            "observed_at": obs.observed_at,
            "key": key,
        },
    ).one_or_none()

    if inserted is None:
        stats.price_events_duplicate += 1
    else:
        stats.price_events_inserted += 1


def record_stock_event(
    session: Session,
    product_id: int,
    retailer_id: int | None,
    record: NormalizedRecord,
    stats: CDCStats,
) -> None:
    obs = record.stock
    if obs is None:
        return

    stats.partitions_created.add(ensure_partition(session, "stock_events", obs.observed_at))

    previous = session.execute(
        text("""
            select in_stock, quantity, observed_at
            from stock_events
            where product_id = :pid
              and retailer_id is not distinct from :rid
              and observed_at <= :observed_at
            order by observed_at desc
            limit 1
        """),
        {"pid": product_id, "rid": retailer_id, "observed_at": obs.observed_at},
    ).one_or_none()

    if previous is not None:
        unchanged = previous.in_stock == obs.in_stock and previous.quantity == obs.quantity
        if unchanged and obs.observed_at - previous.observed_at < HEARTBEAT:
            return

    key = idempotency_key(
        source=record.identity.source,
        external_id=record.identity.external_id,
        observed_at=obs.observed_at,
        kind="stock",
        discriminator=record.retailer_name,
    )
    inserted = session.execute(
        text("""
            insert into stock_events
                (product_id, retailer_id, in_stock, quantity, observed_at, idempotency_key)
            values (:pid, :rid, :in_stock, :quantity, :observed_at, :key)
            on conflict (idempotency_key, observed_at) do nothing
            returning event_id
        """),
        {
            "pid": product_id,
            "rid": retailer_id,
            "in_stock": obs.in_stock,
            "quantity": obs.quantity,
            "observed_at": obs.observed_at,
            "key": key,
        },
    ).one_or_none()
    if inserted is not None:
        stats.stock_events_inserted += 1


def apply_record(
    session: Session, source_id: int, record: NormalizedRecord, stats: CDCStats
) -> None:
    product_id, created = upsert_product(session, source_id, record)
    if created:
        stats.products_created += 1

    if apply_scd2_version(session, product_id, record):
        stats.versions_opened += 1

    retailer_id = None
    if record.retailer_name:
        retailer_id = get_or_create_retailer(
            session,
            source_id,
            record.retailer_name,
            (record.attributes.attributes or {}).get("location_country"),
        )

    record_price_event(session, product_id, retailer_id, record, stats)
    record_stock_event(session, product_id, retailer_id, record, stats)


def now_utc() -> datetime:
    return datetime.now(UTC)
