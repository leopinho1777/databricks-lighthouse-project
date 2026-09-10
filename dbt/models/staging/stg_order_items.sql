-- Model: stg_order_items (staging)
-- Purpose: Order line items standardized from bronze.

with source as (

    select * from {{ source('bronze', 'order_items') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'order_id',
            'product_variant_id',
            'quantity',
            'line_total',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys (IDs) with explicit casts to keep JOINs consistent
        cast(id as string) as order_item_id,
        cast(order_id as string) as order_id,
        cast(product_variant_id as string) as product_variant_id,

        -- Quantity and amount metrics
        cast(quantity as int) as quantity,
        cast(unit_price as decimal(18, 2)) as unit_price,
        cast(line_total as decimal(18, 2)) as line_total,

        -- Taxes (rates converted to standardized decimals when needed)
        cast(icms_rate as decimal(5, 2)) as icms_rate,
        cast(ipi_rate as decimal(5, 2)) as ipi_rate,

        -- Audit metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        cast(_source_origin as string) as _source_origin,
        cast(_batch_id as string) as _batch_id

    from cleaned_required

),

valid_orders_only as (

    {{ filter_valid_orders('renamed') }}

)

select * from valid_orders_only