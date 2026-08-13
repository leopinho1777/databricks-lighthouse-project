{% set max_date_query %}
    select cast(greatest(max(updated_at), current_date()) as date) as max_date
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

-- Aqui deve se chamar 'calendar_dates' e não 'final'
calendar_dates as (

    select
        cast(date_format(date_day, 'yyyyMMdd') as int) as date_id,
        cast(date_day as date) as date_day,
        extract(year from date_day) as year,
        extract(month from date_day) as month,
        date_format(date_day, 'MMMM') as month_name,
        trunc(date_day, 'MM') as month_start,
        extract(quarter from date_day) as quarter,
        extract(dayofweek from date_day) as day_of_week,
        case when extract(year from date_day) = extract(year from current_date()) then true else false end as is_current_year,
        case when extract(year from date_day) = extract(year from current_date()) - 1 then true else false end as is_previous_year
    from spine

),

dummy_date as (

    -- Registro fictício para vendas com data nula/invalida/futura na origem
    select
        19000101 as date_id,
        cast('1900-01-01' as date) as date_day,
        1900 as year,
        1 as month,
        'Não informado' as month_name,
        cast('1900-01-01' as date) as month_start,
        1 as quarter,
        1 as day_of_week,
        false as is_current_year,
        false as is_previous_year

),

-- Esta sim é a única CTE chamada 'final'
final as (

    select * from calendar_dates
    union all
    select * from dummy_date

)

select * from final