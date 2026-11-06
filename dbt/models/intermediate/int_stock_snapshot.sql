-- One row per VBO alive on 1 January of each year (validity time). The table the detector works on.
{% set years = range(var('first_year'), var('last_year') + 1) %}
{% for y in years %}
select
    {{ y }} as year,
    *
from {{ ref('stg_vbo_versions') }}
where valid_from <= date '{{ y }}-01-01'
  and (valid_to is null or valid_to > date '{{ y }}-01-01')
  and registration_ended_at is null
qualify row_number() over (partition by id order by version desc, registered_at desc) = 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
