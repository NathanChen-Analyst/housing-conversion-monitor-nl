{% test dbt_utils_unique_combination(model, combination_of) %}
-- Minimal stand-in for dbt_utils.unique_combination_of_columns (no package download needed offline).
select {{ combination_of | join(', ') }}, count(*) as n
from {{ model }}
group by {{ combination_of | join(', ') }}
having count(*) > 1
{% endtest %}
