select
    id, version,
    cast(valid_from as date) as valid_from,
    cast(valid_to as date)   as valid_to,
    registered_at, registration_ended_at, status, bouwjaar
from {{ source('staging', 'pand_versions') }}
qualify row_number() over (partition by id, version, registered_at order by registration_ended_at desc nulls last) = 1
