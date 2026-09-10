-- Test: test_fct_daily_stock_levels_matches_snapshot_7d
-- Fails if, over the last 7 days, fct_daily_stock_levels is missing a snapshot row, carries
-- different values (stock_level_id, quantities, valid_from), or has rows with no snapshot match.

with expected_source as (

    select
        cast(dbt_valid_from as date) as stock_level_day,
        product_variant_id,
        location_id,
        stock_level_id,
        cast(quantity_on_hand as integer) as raw_quantity_on_hand,
        greatest(cast(quantity_on_hand as integer), 0) as physical_quantity_on_hand,
        cast(dbt_valid_from as timestamp) as snapshot_valid_from,
        row_number() over (
            partition by cast(dbt_valid_from as date), product_variant_id, location_id
            order by cast(dbt_valid_from as timestamp) desc
        ) as row_num
    from {{ ref('snap_stock_levels') }}
    where dbt_valid_from is not null
      and cast(dbt_valid_from as date) >= date_sub(current_date(), 7)

),

expected as (

    select
        stock_level_day,
        product_variant_id,
        location_id,
        stock_level_id,
        raw_quantity_on_hand,
        physical_quantity_on_hand,
        snapshot_valid_from
    from expected_source
    where row_num = 1

),

actual as (

    select
        stock_level_day,
        product_variant_id,
        location_id,
        stock_level_id,
        raw_quantity_on_hand,
        physical_quantity_on_hand,
        snapshot_valid_from
    from {{ ref('fct_daily_stock_levels') }}
    where stock_level_day >= date_sub(current_date(), 7)

),

missing_or_changed as (

    select
        'missing_or_changed_in_fact' as issue_type,
        e.stock_level_day,
        e.product_variant_id,
        e.location_id
    from expected as e
    left join actual as a
      on e.stock_level_day = a.stock_level_day
     and e.product_variant_id = a.product_variant_id
     and e.location_id = a.location_id
    where a.stock_level_day is null
       or coalesce(cast(e.stock_level_id as string), '__null__') <> coalesce(cast(a.stock_level_id as string), '__null__')
       or coalesce(cast(e.raw_quantity_on_hand as string), '__null__') <> coalesce(cast(a.raw_quantity_on_hand as string), '__null__')
       or coalesce(cast(e.physical_quantity_on_hand as string), '__null__') <> coalesce(cast(a.physical_quantity_on_hand as string), '__null__')
       or coalesce(cast(e.snapshot_valid_from as string), '__null__') <> coalesce(cast(a.snapshot_valid_from as string), '__null__')

),

unexpected_in_fact as (

    select
        'unexpected_row_in_fact' as issue_type,
        a.stock_level_day,
        a.product_variant_id,
        a.location_id
    from actual as a
    left join expected as e
      on e.stock_level_day = a.stock_level_day
     and e.product_variant_id = a.product_variant_id
     and e.location_id = a.location_id
    where e.stock_level_day is null

)

select * from missing_or_changed
union all
select * from unexpected_in_fact
