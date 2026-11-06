-- Illustrative detector (pattern 1 only, "use change"): a VBO whose previous version had no woonfunctie
-- and whose new version has one. The production detector is private until publication; it writes the same
-- grain (one row per converted dwelling) and plugs in here.
with ordered as (
    select *,
           lag(is_residential) over (partition by id order by version) as prev_residential
    from {{ ref('stg_vbo_versions') }}
    where registration_ended_at is null
),
first_flip as (
    select id as vbo_id, pand_id, valid_from as event_date, registered_at as reg_date, oppervlakte_m2, x, y,
           row_number() over (partition by id order by valid_from) as rn
    from ordered
    where is_residential and prev_residential = false
)
select vbo_id, pand_id, event_date, reg_date, oppervlakte_m2, x, y
from first_flip
where rn = 1
  and year(event_date) between {{ var('first_year') }} and {{ var('last_year') }}
