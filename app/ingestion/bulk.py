"""Set-based CDC for bulk loads.

`cdc.apply_record` issues about five statements per record. Fine locally; over a 298 ms
link a 7,922-record replay works out at 3.3 hours. This stages the batch in a temp table
and does the same work in a fixed number of round trips, whatever the batch size.

Semantics match the row-by-row path exactly, heartbeat and idempotency included.
`tests/integration/test_bulk_matches_rowwise.py` is what keeps the two equal.
"""

from __future__ import annotations

import json
from datetime import UTC

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.cdc import HEARTBEAT, CDCStats
from app.ingestion.idempotency import idempotency_key
from app.models.domain import NormalizedRecord

log = get_logger(__name__)

_CREATE_STAGING = """
create temp table _stg (
  external_id text not null,
  sku text, upc text, mpn text, brand text, category text, tier smallint,
  title text, attributes jsonb,
  retailer_name text, retailer_country text,
  price numeric(12,2), currency text,
  observed_at timestamptz not null,
  idem text not null
) on commit drop
"""

# One round trip regardless of batch size: arrays are unnested server-side.
_LOAD_STAGING = """
insert into _stg (
  external_id, sku, upc, mpn, brand, category, tier,
  title, attributes, retailer_name, retailer_country,
  price, currency, observed_at, idem
)
select * from unnest(
  cast(:external_id as text[]), cast(:sku as text[]), cast(:upc as text[]),
  cast(:mpn as text[]), cast(:brand as text[]), cast(:category as text[]),
  cast(:tier as smallint[]), cast(:title as text[]), cast(:attributes as jsonb[]),
  cast(:retailer_name as text[]), cast(:retailer_country as text[]),
  cast(:price as numeric[]), cast(:currency as text[]),
  cast(:observed_at as timestamptz[]), cast(:idem as text[])
)
"""

# Historical data spans many months; create every partition the batch needs in one call.
_ENSURE_PARTITIONS = """
do $$
declare m date;
begin
  for m in select distinct date_trunc('month', observed_at)::date from _stg loop
    perform ensure_month_partition('price_events', m);
  end loop;
end $$
"""

_UPSERT_PRODUCTS = """
insert into products (source_id, external_id, sku, upc, mpn, brand, category, tier)
select :sid, external_id,
       max(sku), max(upc), max(mpn), max(brand), max(category),
       min(tier)::smallint
from _stg
group by external_id
on conflict (source_id, external_id) do update set
  sku      = coalesce(excluded.sku, products.sku),
  upc      = coalesce(excluded.upc, products.upc),
  mpn      = coalesce(excluded.mpn, products.mpn),
  brand    = coalesce(excluded.brand, products.brand),
  category = coalesce(excluded.category, products.category),
  tier     = excluded.tier
"""

_UPSERT_RETAILERS = """
insert into retailers (source_id, name, country)
select :sid, retailer_name, max(retailer_country)
from _stg
where retailer_name is not null
-- Group rather than SELECT DISTINCT: one retailer name can arrive with differing
-- country values (often null vs set), and ON CONFLICT rejects a command that proposes
-- the same conflict key twice.
group by retailer_name
on conflict (source_id, name) do update set
  country = coalesce(excluded.country, retailers.country)
"""

# Latest incoming attributes per product, joined to the currently-open version.
# A null incoming value inherits the known one, so sparse payloads do not churn versions.
_CHANGED_VERSIONS = """
create temp table _changed on commit drop as
with incoming as (
  select distinct on (p.product_id)
         p.product_id, s.title, s.brand, s.category, s.attributes
  from _stg s
  join products p on p.source_id = :sid and p.external_id = s.external_id
  order by p.product_id, s.observed_at desc
)
select i.product_id,
       coalesce(i.title, c.title)       as title,
       coalesce(i.brand, c.brand)       as brand,
       coalesce(i.category, c.category) as category,
       i.attributes,
       c.version_id as old_version_id
from incoming i
left join product_versions c
       on c.product_id = i.product_id and c.is_current
where c.version_id is null
   or (coalesce(i.title, c.title),
       coalesce(i.brand, c.brand),
       coalesce(i.category, c.category))
      is distinct from (c.title, c.brand, c.category)
"""

_CLOSE_VERSIONS = """
update product_versions pv
set is_current = false, valid_to = now()
from _changed c
where pv.version_id = c.old_version_id
"""

_OPEN_VERSIONS = """
insert into product_versions
  (product_id, title, brand, category, attributes, valid_from, is_current)
select product_id, title, brand, category, attributes, now(), true
from _changed
"""

# Insert-on-change, set-based. Existing history and incoming rows are unioned so the
# window function can see the observation preceding each candidate, which is what makes
# late-arriving/backfilled data compare against the right neighbour rather than the newest row.
_INSERT_PRICE_EVENTS = """
with joined as (
  select p.product_id,
         r.retailer_id,
         s.price, s.currency, s.observed_at, s.idem
  from _stg s
  join products p on p.source_id = :sid and p.external_id = s.external_id
  left join retailers r on r.source_id = :sid and r.name = s.retailer_name
  where s.price is not null
),
pairs as (
  select distinct product_id, retailer_id from joined
),
history as (
  select pe.product_id, pe.retailer_id, pe.price, pe.observed_at,
         null::text as currency, null::text as idem, true as existing
  from price_events pe
  join pairs k
    on k.product_id = pe.product_id
   and k.retailer_id is not distinct from pe.retailer_id
  union all
  select product_id, retailer_id, price, observed_at, currency, idem, false
  from joined
),
ranked as (
  select h.*,
         lag(price)       over w as prev_price,
         lag(observed_at) over w as prev_at
  from history h
  window w as (partition by product_id, retailer_id order by observed_at, existing desc)
)
insert into price_events
  (product_id, retailer_id, price, currency, observed_at, idempotency_key)
select product_id, retailer_id, price, coalesce(currency, 'USD'), observed_at, idem
from ranked
where not existing
  and (
    prev_price is null
    or prev_price <> price
    or observed_at - prev_at >= cast(:heartbeat as interval)
  )
on conflict (idempotency_key, observed_at) do nothing
"""


def apply_records_bulk(
    session: Session, source_id: int, records: list[NormalizedRecord]
) -> CDCStats:
    """Apply a batch of normalized records in a constant number of round trips."""
    stats = CDCStats()
    priced = [r for r in records if r.price is not None]
    if not priced:
        return stats

    cols: dict[str, list] = {
        k: []
        for k in (
            "external_id",
            "sku",
            "upc",
            "mpn",
            "brand",
            "category",
            "tier",
            "title",
            "attributes",
            "retailer_name",
            "retailer_country",
            "price",
            "currency",
            "observed_at",
            "idem",
        )
    }

    for r in priced:
        ident, attrs, price = r.identity, r.attributes, r.price
        extra = attrs.attributes or {}
        cols["external_id"].append(ident.external_id)
        cols["sku"].append(ident.sku)
        cols["upc"].append(ident.upc)
        cols["mpn"].append(ident.mpn)
        cols["brand"].append(ident.brand)
        cols["category"].append(ident.category)
        cols["tier"].append(ident.tier)
        cols["title"].append(attrs.title)
        cols["attributes"].append(json.dumps(extra, default=str))
        cols["retailer_name"].append(r.retailer_name)
        cols["retailer_country"].append(extra.get("location_country"))
        cols["price"].append(price.price)
        cols["currency"].append(price.currency)
        cols["observed_at"].append(price.observed_at.astimezone(UTC))
        cols["idem"].append(
            idempotency_key(
                source=ident.source,
                external_id=ident.external_id,
                observed_at=price.observed_at,
                kind="price",
                discriminator=r.retailer_name,
            )
        )

    before = session.execute(text("select count(*) from price_events")).scalar_one()

    session.execute(text(_CREATE_STAGING))
    session.execute(text(_LOAD_STAGING), cols)
    session.execute(text(_ENSURE_PARTITIONS))
    session.execute(text(_UPSERT_PRODUCTS), {"sid": source_id})
    session.execute(text(_UPSERT_RETAILERS), {"sid": source_id})
    session.execute(text(_CHANGED_VERSIONS), {"sid": source_id})
    stats.versions_opened = session.execute(text("select count(*) from _changed")).scalar_one()
    session.execute(text(_CLOSE_VERSIONS))
    session.execute(text(_OPEN_VERSIONS))
    session.execute(
        text(_INSERT_PRICE_EVENTS),
        {"sid": source_id, "heartbeat": f"{int(HEARTBEAT.total_seconds())} seconds"},
    )

    after = session.execute(text("select count(*) from price_events")).scalar_one()
    stats.price_events_inserted = after - before
    stats.price_events_skipped_unchanged = len(priced) - stats.price_events_inserted

    log.info(
        "bulk.applied",
        records=len(priced),
        inserted=stats.price_events_inserted,
        versions_opened=stats.versions_opened,
    )
    return stats
