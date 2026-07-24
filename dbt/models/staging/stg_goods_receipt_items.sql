with source as (

    select * from {{ source('bronze', 'goods_receipt_items') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'goods_receipt_id',
            'purchase_order_item_id',
            'quantity_received',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as goods_receipt_item_id,
        goods_receipt_id,
        purchase_order_item_id,

        -- Attributes
        cast(quantity_received as decimal(14, 3)) as quantity_received,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed
