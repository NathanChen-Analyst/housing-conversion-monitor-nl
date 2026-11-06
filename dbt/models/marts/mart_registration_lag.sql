-- How late do municipalities register? Distribution of (registered_at - valid_from) per year of validity.
-- This is the fact behind using registration time for anything a forecast is allowed to see.
select
    year(valid_from)                                                        as year,
    count(*)                                                                as versions,
    quantile_cont(date_diff('day', valid_from, cast(registered_at as date)), 0.5)  as p50_days,
    quantile_cont(date_diff('day', valid_from, cast(registered_at as date)), 0.9)  as p90_days,
    max(date_diff('day', valid_from, cast(registered_at as date)))              as max_days
from {{ ref('stg_vbo_versions') }}
where year(valid_from) between {{ var('first_year') }} and {{ var('last_year') }}
group by 1
order by 1
