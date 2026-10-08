with gaps as (select * from {{ ref('mart_price_gap_vs_own') }})

select
    product_id,
    retailer_id,
    upc,
    our_sku,
    product_name,
    category,
    retailer_name,
    currency,
    our_price,
    competitor_price,
    gap_abs,
    gap_pct,
    latest_observed_date,
    days_stale,
    case
        when gap_pct <= -20 then 'critical'
        when gap_pct <= -10 then 'high'
        when gap_pct <   0  then 'medium'
        else 'low'
    end as severity,
    case
        when days_stale <= 1  then 'fresh'
        when days_stale <= 7  then 'recent'
        else 'stale'
    end as confidence
from gaps
where is_undercut
  and days_stale <= {{ var('active_undercut_max_days', 365) }}
