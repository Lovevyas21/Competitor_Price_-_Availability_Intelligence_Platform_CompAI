-- One price per product / retailer / currency / day.
--
-- Several observations can land on the same day (different contributors, a re-fetch, a
-- corrected entry). Marts need a single defensible number per day, so the last
-- observation of the day wins -- it is the most recent information available.
with observations as (select * from {{ ref('int_price_observations') }}),

ranked as (
    select
        *,
        row_number() over (
            partition by product_id, retailer_id, currency, observed_date
            order by observed_at desc, event_id desc
        ) as recency_rank,
        count(*) over (
            partition by product_id, retailer_id, currency, observed_date
        ) as observations_that_day
    from observations
)

select
    product_id,
    retailer_id,
    external_id,
    sku,
    upc,
    tier,
    source_name,
    retailer_name,
    retailer_country,
    title,
    brand,
    category,
    currency,
    price                  as close_price,
    observed_at            as last_observed_at,
    observed_date,
    observations_that_day
from ranked
where recency_rank = 1
