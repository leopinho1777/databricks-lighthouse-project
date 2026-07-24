{% set max_date_query %}
    select cast(max(updated_at) as date) as max_date
    from lh_nautical.bronze._ingestion_control
{% endset %}

{% if execute %}
    {% set max_date_results = run_query(max_date_query) %}
    {% set max_date = max_date_results.columns[0].values()[0] %}
{% else %}
    {% set max_date = '2099-12-31' %}
{% endif %}

with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2020-01-01' as date)",
        end_date="cast('" ~ max_date ~ "' as date)"
    ) }}
),
final as (
    select
        date_day as date_id,
        date_day,
        extract(year from date_day) as year,
        extract(month from date_day) as month,
        extract(quarter from date_day) as quarter,
        extract(dayofweek from date_day) as day_of_week
    from spine
)
select * from final