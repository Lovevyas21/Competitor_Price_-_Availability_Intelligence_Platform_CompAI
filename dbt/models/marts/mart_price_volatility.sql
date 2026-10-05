with daily as (select * from {{ ref('int_price_daily') }}),

stats as (
    select
        product_id,
        retailer_id,
        currency,
        max(external_id)      as external_id,
        max(upc)              as upc,
        max(title)            as title,
        max(brand)            as brand,
        max(category)         as category,
        max(retailer_name)    as retailer_name,
        max(tier)             as tier,
        count(*)              as observation_count,
        min(observed_date)    as first_observed_date,
        max(observed_date)    as last_observed_date,
        min(close_price)      as min_price,
        max(close_price)      as max_price,
        avg(close_price)      as mean_price,
        stddev_samp(close_price) as stddev_price
    from daily
    group by product_id, retailer_id, currency
    having count(*) >= {{ var('min_observations_for_volatility') }}
)

select
    product_id,
    retailer_id,
    external_id,
    upc,
    title,
    brand,
    category,
    retailer_name,
    tier,
    currency,
    observation_count,
    first_observed_date,
    last_observed_date,
    round(min_price, 2)                                       as min_price,
    round(max_price, 2)                                       as max_price,
    round(mean_price, 2)                                      as mean_price,
    round(coalesce(stddev_price, 0), 4)                       as stddev_price,
    round(max_price - min_price, 2)                           as price_range,
    round(coalesce(stddev_price, 0) / nullif(mean_price, 0), 4) as coefficient_of_variation,
    case
        when coalesce(stddev_price, 0) / nullif(mean_price, 0) >= 0.20 then 'high'
        when coalesce(stddev_price, 0) / nullif(mean_price, 0) >= 0.05 then 'medium'
        else 'low'
    end                                                        as volatility_band
from stats
