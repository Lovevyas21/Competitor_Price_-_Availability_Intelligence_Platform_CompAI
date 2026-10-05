select
    event_id,
    product_id,
    retailer_id,
    price,
    upper(currency)              as currency,
    observed_at,
    observed_at::date            as observed_date,
    ingested_at,
    idempotency_key
from {{ source('cpi', 'price_events') }}
where price >= 0
