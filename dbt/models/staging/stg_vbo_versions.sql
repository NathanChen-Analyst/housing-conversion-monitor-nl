-- Latest copy of every (id, version, registered_at); a mutation may re-emit a row with registration_ended_at set.
with src as (
    select * from {{ source('staging', 'vbo_versions') }}
)
select
    id,
    version,
    cast(valid_from as date)               as valid_from,
    cast(valid_to as date)                 as valid_to,
    registered_at,
    registration_ended_at,
    status,
    gebruiksdoel,
    list_contains(string_split(lower(coalesce(gebruiksdoel, '')), ','), 'woonfunctie') as is_residential,
    list_contains(string_split(lower(coalesce(gebruiksdoel, '')), ','), 'kantoorfunctie') as is_office,
    oppervlakte_m2,
    pand_id,
    x, y
from src
qualify row_number() over (partition by id, version, registered_at order by registration_ended_at desc nulls last) = 1
