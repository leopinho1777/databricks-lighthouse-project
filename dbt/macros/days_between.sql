{% macro days_between(start_date, end_date) %}
    datediff(cast({{ end_date }} as date), cast({{ start_date }} as date))
{% endmacro %}