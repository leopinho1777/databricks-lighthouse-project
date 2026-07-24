{{
    config(
        materialized='incremental',
        unique_key=['stock_level_day', 'product_variant_id', 'location_id'],
        incremental_strategy='merge',
        file_format='delta',
        on_schema_change='sync_all_columns'
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
        stock_level_day,
        product_variant_id,
        location_id,
        stock_level_id,
        raw_quantity_on_hand,
        physical_quantity_on_hand,
        raw_quantity_on_hand < 0 as is_negative_raw_quantity,
        source_updated_at,
        snapshot_valid_from,
        snapshot_valid_to,
        _ingested_at,
        _source_origin,
        _batch_id
    from latest_change_per_day
    where row_num = 1

)

select * from final
