-- Competitor price versus our own catalogue price, per retailer.
--
-- Matching is on UPC/barcode, never on name: an exact structured identifier is the only
-- match we trust without human review (embedding-based matching lands in phase 5).
--
-- The join is scoped to a matching currency. Subtracting a SEK price from a EUR price
-- would produce a number that looks authoritative and means nothing, so cross-currency
-- rows are simply not produced.
with latest as (select * from {{ ref('int_price_latest') }}),

own as (
    select
        match_upc,
        our_sku,
        product_name,
        our_price,
        upper(currency) as currency
    from {{ ref('own_catalog') }}
    where active
)

select
    l.product_id,
    l.retailer_id,
    l.upc,
    o.our_sku,
    coalesce(l.title, o.product_name)     as product_name,
    l.brand,
    l.category,
    l.tier,
    l.source_name,
    l.retailer_name,
    l.retailer_country,
    l.currency,
    o.our_price,
    l.latest_price                        as competitor_price,
    round(l.latest_price - o.our_price, 2) as gap_abs,
    round(100.0 * (l.latest_price - o.our_price) / nullif(o.our_price, 0), 2) as gap_pct,
    -- Negative gap = competitor is cheaper = they are undercutting us.
    case
        when l.latest_price < o.our_price * {{ var('undercut_threshold') }} then true
        else false
    end                                   as is_undercut,
    l.latest_observed_date,
    l.days_stale
from latest l
inner join own o
    on o.match_upc = l.upc
   and o.currency  = l.currency
