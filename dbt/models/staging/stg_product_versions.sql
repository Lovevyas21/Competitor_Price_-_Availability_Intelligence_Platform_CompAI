select
    version_id,
    product_id,
    nullif(trim(title), '')    as title,
    nullif(trim(brand), '')    as brand,
    nullif(trim(category), '') as category,
    attributes,
    valid_from,
    valid_to,
    is_current
from {{ source('cpi', 'product_versions') }}
