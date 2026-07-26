{{ config(severity='warn') }}

with movement_daily as (

    select
        cast(occurred_at as date) as stock_day,
        product_variant_id,
        location_id,
        sum(quantity) as net_movement
    from {{ ref('stg_stock_movements') }}
    where cast(occurred_at as date) >= date_sub(current_date(), 7)
    group by 1, 2, 3

),

snapshot_daily as (

    select
        cast(dbt_valid_from as date) as stock_day,
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

snapshot_latest as (

    select
        stock_day,
        product_variant_id,
        location_id
    from snapshot_daily
    where row_num = 1

),

pairing as (

    select
        coalesce(m.stock_day, s.stock_day) as stock_day,
        coalesce(m.product_variant_id, s.product_variant_id) as product_variant_id,
        coalesce(m.location_id, s.location_id) as location_id,
        m.net_movement,
        case when m.stock_day is null then 0 else 1 end as has_movement,
        case when s.stock_day is null then 0 else 1 end as has_snapshot,
        case
            when m.stock_day is null or s.stock_day is null then 1
            else 0
        end as unknown_pairing_flag
    from movement_daily as m
    full outer join snapshot_latest as s
      on m.stock_day = s.stock_day
     and m.product_variant_id = s.product_variant_id
     and m.location_id = s.location_id

),

quality_by_day as (

    select
        stock_day,
        cast(sum(unknown_pairing_flag) as double) / nullif(cast(count(*) as double), 0) as unknown_ratio_day,
        sum(case when has_movement = 1 and has_snapshot = 0 and coalesce(net_movement, 0) = 0 then 1 else 0 end) as movement_without_snapshot_net_zero_rows,
        sum(case when has_movement = 1 and has_snapshot = 0 and coalesce(net_movement, 0) <> 0 then 1 else 0 end) as movement_without_snapshot_nonzero_rows,
        sum(case when has_movement = 0 and has_snapshot = 1 then 1 else 0 end) as snapshot_without_movement_rows
    from pairing
    group by 1

)

select *
from quality_by_day
where unknown_ratio_day > 0
