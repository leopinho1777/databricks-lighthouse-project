{{
    config(
        materialized='incremental',
        unique_key=['stock_level_day', 'product_variant_id', 'location_id'],
        incremental_strategy='merge',
        file_format='delta',
        on_schema_change='sync_all_columns',
        post_hook=[
            "update {{ this }} set zero_quantity_movement_count = coalesce(zero_quantity_movement_count, 0), has_zero_quantity_movement_review = coalesce(has_zero_quantity_movement_review, false) where zero_quantity_movement_count is null or has_zero_quantity_movement_review is null"
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
        l.product_variant_id,
        l.location_id,
        l.stock_level_id,
        l.raw_quantity_on_hand,
        l.physical_quantity_on_hand,
        l.raw_quantity_on_hand < 0 as is_negative_raw_quantity,
        coalesce(z.zero_quantity_movement_count, 0) as zero_quantity_movement_count,
        coalesce(z.zero_quantity_movement_count, 0) > 0 as has_zero_quantity_movement_review,
        l.source_updated_at,
        l.snapshot_valid_from,
        l.snapshot_valid_to,
        l._ingested_at,
        l._source_origin,
        l._batch_id
    from latest_change_per_day as l
    left join zero_quantity_movement_daily as z
      on l.stock_level_day = z.stock_level_day
     and l.product_variant_id = z.product_variant_id
     and l.location_id = z.location_id
    where l.row_num = 1

)

select * from final
