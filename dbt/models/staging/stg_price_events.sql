-- One row per observed price.
--
-- `currency` is carried through everywhere downstream and is never dropped: this data
-- spans EUR, SEK, USD, PLN and NOK, and comparing across them without conversion would
-- produce confident nonsense. Every comparison downstream is scoped to one currency.
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
