-- Price events enriched with product, retailer and current-title context.
--
-- This is the single join every mart builds on, so the join logic lives in one place
-- rather than being repeated (and drifting) across marts.
with prices as (select * from {{ ref('stg_price_events') }}),

products as (select * from {{ ref('stg_products') }}),

retailers as (select * from {{ ref('stg_retailers') }}),

sources as (select * from {{ ref('stg_sources') }}),

current_version as (
    select product_id, title, brand, category
    from {{ ref('stg_product_versions') }}
    where is_current
)

select
    p.event_id,
    p.product_id,
    p.retailer_id,
    pr.external_id,
    pr.sku,
    pr.upc,
    pr.tier,
    s.source_name,
    coalesce(r.retailer_name, 'unknown')            as retailer_name,
    r.country                                       as retailer_country,
    cv.title,
    coalesce(cv.brand, pr.brand)                    as brand,
    coalesce(cv.category, pr.category)              as category,
    p.price,
    p.currency,
    p.observed_at,
    p.observed_date
from prices p
inner join products  pr on pr.product_id  = p.product_id
inner join sources   s  on s.source_id    = pr.source_id
left  join retailers r  on r.retailer_id  = p.retailer_id
left  join current_version cv on cv.product_id = p.product_id
