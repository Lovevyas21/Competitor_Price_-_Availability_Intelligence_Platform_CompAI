select
    source_id,
    name as source_name,
    base_url,
    auth_type,
    created_at
from {{ source('cpi', 'sources') }}
