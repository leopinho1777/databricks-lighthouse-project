-- Model: stg_return_items (staging)
-- Purpose: Return items line-level details standardized from bronze.

with source as (

    select * from {{ source('bronze', 'return_items') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'return_id',
            'order_item_id',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as return_item_id,
        return_id,
        order_item_id,
        exchange_variant_id,

        -- Attributes
        cast(quantity as integer) as quantity,
        lower(trim(action)) as action,

        -- Amounts
        cast(unit_refund_amount as decimal(18, 2)) as unit_refund_amount,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed