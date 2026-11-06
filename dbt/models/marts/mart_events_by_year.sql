-- National series: dwellings converted per year, with year-on-year change and share of the period.
with e as (
    select year(event_date) as year, count(*) as n
    from {{ ref('int_conversion_events') }}
    group by 1
)
select year, n,
       n - lag(n) over (order by year)                         as yoy_change,
       round(100.0 * n / sum(n) over (), 2)                     as share_pct
from e
order by year
