-- Out-of-stock rate per product / retailer.
--
-- Currently returns zero rows: neither keyless source (Fake Store, Open Prices) reports
-- availability, so `stock_events` is empty. The model is written against the real schema
-- so it starts producing numbers the moment a stock-bearing source -- Best Buy or
-- Digi-Key -- is connected, rather than being invented later under time pressure.
with stock as (select * from {{ ref('stg_stock_events') }}),

products as (select * from {{ ref('stg_products') }}),

retailers as (select * from {{ ref('stg_retailers') }}),

daily as (
    select
        product_id,
        retailer_id,
        observed_date,
        -- A day counts as out of stock if any observation that day said so.
        bool_or(not coalesce(in_stock, true)) as was_out_of_stock
    from stock
    group by product_id, retailer_id, observed_date
),

agg as (
    select
        product_id,
        retailer_id,
        count(*)                                as days_observed,
        count(*) filter (where was_out_of_stock) as days_out_of_stock,
        min(observed_date)                      as first_observed_date,
        max(observed_date)                      as last_observed_date
    from daily
    group by product_id, retailer_id
)

select
    a.product_id,
    a.retailer_id,
    p.external_id,
    p.upc,
    p.category,
    p.tier,
    r.retailer_name,
    a.days_observed,
    a.days_out_of_stock,
    round(100.0 * a.days_out_of_stock / nullif(a.days_observed, 0), 2) as out_of_stock_pct,
    a.first_observed_date,
    a.last_observed_date
from agg a
inner join products  p on p.product_id  = a.product_id
left  join retailers r on r.retailer_id = a.retailer_id
