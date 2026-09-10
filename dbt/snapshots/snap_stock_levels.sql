-- Snapshot: snap_stock_levels
-- Purpose: SCD2 history of stg_stock_levels (timestamp strategy on updated_at, keyed on
--          stock_level_id, hard deletes invalidated). Feeds fct_daily_stock_levels.

{% snapshot snap_stock_levels %}

{{
    config(
        target_schema='snapshots',
        unique_key='stock_level_id',
        strategy='timestamp',
        updated_at='updated_at',
        invalidate_hard_deletes=True
    )
}}

select
    stock_level_id,
    product_variant_id,
    location_id,
    quantity_on_hand,
    updated_at,
    _ingested_at,
    _source_origin,
    _batch_id
from {{ ref('stg_stock_levels') }}

{% endsnapshot %}
