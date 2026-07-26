{{ config(severity='warn') }}

with movement_base as (

    select
        cast(occurred_at as date) as stock_day,
        product_variant_id,
        location_id,
        movement_type,
        abs(cast(quantity as integer)) as quantity_abs
    from {{ ref('stg_stock_movements') }}
    where cast(occurred_at as date) >= date_sub(current_date(), 7)

),

movement_daily as (

    select
        stock_day,
        product_variant_id,
        location_id,
        sum(
            case
                when movement_type in ('purchase_in', 'return_in') then quantity_abs
                when movement_type in ('sale_out', 'return_out') then -quantity_abs
                else 0
            end
        ) as net_movement_expected
    from movement_base
    group by 1, 2, 3

),

snapshot_daily_source as (

    select
        cast(dbt_valid_from as date) as stock_day,
        product_variant_id,
        location_id,
        cast(quantity_on_hand as integer) as closing_stock_snapshot,
        cast(dbt_valid_from as timestamp) as snapshot_valid_from,
        row_number() over (
            partition by cast(dbt_valid_from as date), product_variant_id, location_id
            order by cast(dbt_valid_from as timestamp) desc
        ) as row_num
    from {{ ref('snap_stock_levels') }}
    where dbt_valid_from is not null
      and cast(dbt_valid_from as date) >= date_sub(current_date(), 8)

),

snapshot_daily as (

    select
        stock_day,
        product_variant_id,
        location_id,
        closing_stock_snapshot,
        snapshot_valid_from
    from snapshot_daily_source
    where row_num = 1

),

snapshot_with_opening as (

    select
        stock_day,
        product_variant_id,
        location_id,
        closing_stock_snapshot,
        snapshot_valid_from,
        lag(closing_stock_snapshot) over (
            partition by product_variant_id, location_id
            order by stock_day
        ) as opening_stock_snapshot
    from snapshot_daily

),

recon_universe as (

    select
        coalesce(m.stock_day, s.stock_day) as stock_day,
        coalesce(m.product_variant_id, s.product_variant_id) as product_variant_id,
        coalesce(m.location_id, s.location_id) as location_id,
        s.opening_stock_snapshot,
        m.net_movement_expected,
        case
            when s.opening_stock_snapshot is not null then s.opening_stock_snapshot + coalesce(m.net_movement_expected, 0)
        end as closing_stock_expected,
        s.closing_stock_snapshot,
        case
            when s.opening_stock_snapshot is not null and s.closing_stock_snapshot is not null
                then s.closing_stock_snapshot - (s.opening_stock_snapshot + coalesce(m.net_movement_expected, 0))
        end as delta_diff,
        case
            when s.stock_day is null and coalesce(m.net_movement_expected, 0) = 0 then 'movement_without_snapshot_net_zero'
            when s.stock_day is null then 'missing_snapshot_for_nonzero_movement'
            when m.stock_day is null then 'snapshot_without_movement'
            when s.opening_stock_snapshot is null then 'missing_opening_snapshot'
            when s.closing_stock_snapshot <> (s.opening_stock_snapshot + coalesce(m.net_movement_expected, 0)) then 'value_mismatch'
            else 'ok'
        end as mismatch_category,
        case
            when m.stock_day is null or s.stock_day is null then 1
            else 0
        end as unknown_pairing_flag
    from movement_daily as m
    full outer join snapshot_with_opening as s
      on m.stock_day = s.stock_day
     and m.product_variant_id = s.product_variant_id
     and m.location_id = s.location_id
    where coalesce(m.stock_day, s.stock_day) >= date_sub(current_date(), 7)

),

unknown_ratio_by_day as (

    select
        stock_day,
        cast(sum(unknown_pairing_flag) as double) / nullif(cast(count(*) as double), 0) as unknown_ratio_day
    from recon_universe
    group by 1

),

final as (

    select
        r.stock_day,
        r.product_variant_id,
        r.location_id,
        r.opening_stock_snapshot,
        r.net_movement_expected,
        r.closing_stock_expected,
        r.closing_stock_snapshot,
        r.delta_diff,
        r.mismatch_category,
        u.unknown_ratio_day
    from recon_universe as r
    left join unknown_ratio_by_day as u
      on r.stock_day = u.stock_day

)

select *
from final
where mismatch_category in (
    'missing_snapshot_for_nonzero_movement',
    'snapshot_without_movement',
    'value_mismatch'
)
