{{
    config(
        materialized='incremental',
        unique_key=['stock_level_day', 'product_variant_id', 'location_id'],
        incremental_strategy='insert_overwrite',
        file_format='delta',
        post_hook=[
            "update {{ this }} set zero_quantity_movement_count = coalesce(zero_quantity_movement_count, 0), has_zero_quantity_movement_review = coalesce(has_zero_quantity_movement_review, false) where zero_quantity_movement_count is null or has_zero_quantity_movement_review is null",
            "merge into {{ this }} as target
             using (
                 select
                     l.product_variant_id,
                     l.location_id,
                     p.product_variant_sk,
                     loc.location_sk
                 from (
                     select distinct product_variant_id, location_id
                     from {{ this }}
                     where product_variant_sk is null or location_sk is null
                 ) as l
                 left join {{ ref('dim_products') }} as p on l.product_variant_id = p.product_variant_id
                 left join {{ ref('dim_locations') }} as loc on l.location_id = loc.location_id
             ) as source
             on target.product_variant_id = source.product_variant_id
                and target.location_id = source.location_id
             when matched and (target.product_variant_sk is null or target.location_sk is null) then update set
                 target.product_variant_sk = coalesce(target.product_variant_sk, source.product_variant_sk),
                 target.location_sk = coalesce(target.location_sk, source.location_sk)"
        ]
    )
}}

with snapshot_history as (

    select
        stock_level_id,
        product_variant_id,
        location_id,
        cast(quantity_on_hand as integer) as raw_quantity_on_hand,
        greatest(cast(quantity_on_hand as integer), 0) as physical_quantity_on_hand,
        cast(dbt_valid_from as date) as stock_level_day,
        cast(updated_at as timestamp) as source_updated_at,
        cast(dbt_valid_from as timestamp) as snapshot_valid_from,
        cast(dbt_valid_to as timestamp) as snapshot_valid_to,
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id
    from {{ ref('snap_stock_levels') }}
    where dbt_valid_from is not null

    {% if is_incremental() %}
      and cast(dbt_valid_from as date) >= date_sub(current_date(), 7)
    {% endif %}

),

zero_quantity_movement_daily as (

        select
                cast(occurred_at as date) as stock_level_day,
                product_variant_id,
                location_id,
                count(*) as zero_quantity_movement_count
        from {{ ref('stg_stock_movements') }}
        where is_zero_quantity_movement

        {% if is_incremental() %}
            and cast(occurred_at as date) >= date_sub(current_date(), 7)
        {% endif %}

        group by 1, 2, 3

),

products as (

    select
        product_variant_sk,
        product_variant_id
    from {{ ref('dim_products') }}

),

locations as (

    select
        location_sk,
        location_id
    from {{ ref('dim_locations') }}

),

latest_change_per_day as (

    select
        *,
        row_number() over (
            partition by stock_level_day, product_variant_id, location_id
            order by snapshot_valid_from desc
        ) as row_num
    from snapshot_history

),

final as (

    select
        l.stock_level_day,
        p.product_variant_sk,
        l.product_variant_id,
        loc.location_sk,
        l.location_id,
        l.stock_level_id,
        l.raw_quantity_on_hand,
        l.physical_quantity_on_hand,
        l.raw_quantity_on_hand < 0 as is_negative_raw_quantity,
        coalesce(z.zero_quantity_movement_count, 0) as zero_quantity_movement_count,
        coalesce(z.zero_quantity_movement_count, 0) > 0 as has_zero_quantity_movement_review,
        l.source_updated_at,
        l.snapshot_valid_from,
        l.snapshot_valid_to
    from latest_change_per_day as l
    left join zero_quantity_movement_daily as z
      on l.stock_level_day = z.stock_level_day
     and l.product_variant_id = z.product_variant_id
     and l.location_id = z.location_id
    left join products as p
      on l.product_variant_id = p.product_variant_id
    left join locations as loc
      on l.location_id = loc.location_id
    where l.row_num = 1

)

select * from final
