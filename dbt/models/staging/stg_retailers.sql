with source as (select * from {{ source('cpi', 'retailers') }})

select
    retailer_id,
    source_id,
    nullif(trim(name), '') as retailer_name,
    country,
    created_at
from source
