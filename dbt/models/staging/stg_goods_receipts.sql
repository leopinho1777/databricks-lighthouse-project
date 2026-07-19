with source as (

    select * from {{ source('bronze', 'goods_receipts') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'purchase_order_id',
            'received_by_employee_id',
            'received_at',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as goods_receipt_id,
        purchase_order_id,
        received_by_employee_id,

        -- Attributes
        notes,

        -- Timestamps (Fundamentais para análise de lead time de entrega)
        cast(received_at as timestamp) as received_at,
        cast(created_at as timestamp) as created_at,

        -- Metadata (Garantindo linhagem com desempate determinístico)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed