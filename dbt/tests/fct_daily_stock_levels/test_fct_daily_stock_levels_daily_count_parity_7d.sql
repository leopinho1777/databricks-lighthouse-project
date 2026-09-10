-- Test: test_fct_daily_stock_levels_daily_count_parity_7d
-- Fails if, on any of the last 7 days, the row count in fct_daily_stock_levels differs from
-- the number of product/location pairs that changed in snap_stock_levels that day.

with expected_source as (

    select
        cast(dbt_valid_from as date) as stock_level_day,
        product_variant_id,
        location_id,
        row_number() over (
            partition by cast(dbt_valid_from as date), product_variant_id, location_id
            order by cast(dbt_valid_from as timestamp) desc
        ) as row_num
    from {{ ref('snap_stock_levels') }}
    where dbt_valid_from is not null
      and cast(dbt_valid_from as date) >= date_sub(current_date(), 7)

),

expected_by_day as (

    select
        stock_level_day,
        count(*) as expected_count
    from expected_source
    where row_num = 1
    group by 1

),

actual_by_day as (

    select
        stock_level_day,
        count(*) as actual_count
    from {{ ref('fct_daily_stock_levels') }}
    where stock_level_day >= date_sub(current_date(), 7)
    group by 1

),

comparison as (

    select
        coalesce(e.stock_level_day, a.stock_level_day) as stock_level_day,
        coalesce(e.expected_count, 0) as expected_count,
        coalesce(a.actual_count, 0) as actual_count
    from expected_by_day as e
    full outer join actual_by_day as a
      on e.stock_level_day = a.stock_level_day

)

select *
from comparison
where expected_count <> actual_count
