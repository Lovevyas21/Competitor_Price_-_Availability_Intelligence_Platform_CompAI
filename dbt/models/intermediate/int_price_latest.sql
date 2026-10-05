with daily as (select * from {{ ref('int_price_daily') }}),

ranked as (
    select
        *,
        row_number() over (
            partition by product_id, retailer_id, currency
            order by observed_date desc
        ) as recency_rank
    from daily
)

select
    product_id,
    retailer_id,
    external_id,
    upc,
    tier,
    source_name,
    retailer_name,
    retailer_country,
    title,
    brand,
    category,
    currency,
    close_price                                          as latest_price,
    observed_date                                        as latest_observed_date,
    last_observed_at,
    (current_date - observed_date)                       as days_stale
from ranked
where recency_rank = 1
