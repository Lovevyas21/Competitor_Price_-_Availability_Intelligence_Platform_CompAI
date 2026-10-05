select
    event_id,
    product_id,
    retailer_id,
    in_stock,
    quantity,
    observed_at,
    observed_at::date as observed_date,
    ingested_at,
    idempotency_key
from {{ source('cpi', 'stock_events') }}
