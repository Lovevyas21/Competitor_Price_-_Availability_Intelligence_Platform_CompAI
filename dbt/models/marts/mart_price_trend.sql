-- Daily price series per product / retailer / currency, with day-over-day change.
--
-- This is the table the forecasting pipeline reads in phase 4 and the shape charts want,
-- so the window logic lives here once rather than being re-derived by each consumer.
with daily as (select * from {{ ref('int_price_daily') }}),

with_lag as (
    select
        *,
        lag(close_price) over w  as prev_price,
        lag(observed_date) over w as prev_observed_date
    from daily
    window w as (
        partition by product_id, retailer_id, currency
        order by observed_date
    )
)

select
    product_id,
    retailer_id,
    external_id,
    upc,
    title,
    brand,
    category,
    tier,
    source_name,
    retailer_name,
    currency,
    observed_date,
    close_price,
    prev_price,
    round(close_price - prev_price, 2) as change_abs,
    round(100.0 * (close_price - prev_price) / nullif(prev_price, 0), 2) as change_pct,
    (observed_date - prev_observed_date) as days_since_previous,
    observations_that_day
from with_lag
