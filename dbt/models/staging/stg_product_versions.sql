-- SCD2 attribute history. `is_current` marks the open version; `valid_to` is null there.
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
