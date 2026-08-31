-- Product identity, one row per tracked product.
with source as (select * from {{ source('cpi', 'products') }})

select
    product_id,
    source_id,
    external_id,
    sku,
    upc,
    mpn,
    nullif(trim(brand), '')    as brand,
    nullif(trim(category), '') as category,
    tier,
    created_at
from source
