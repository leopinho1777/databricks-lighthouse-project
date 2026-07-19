with source as (

    select * from {{ source('bronze', 'purchase_orders') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'supplier_id',
            'buyer_id',
            'destination_location_id',
            'placed_at',
            'total',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as purchase_order_id,
        supplier_id,
        buyer_id,
        destination_location_id,

        -- Attributes
        po_number,
        status as purchase_order_status,
        currency,

        -- Measures
        subtotal,
        total,

        -- Timestamps (Cruciais para os testes de cálculo de intervalo da macro!)
        cast(placed_at as timestamp) as placed_at,
        cast(expected_delivery_at as timestamp) as expected_delivery_at,
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata (Garantindo a linhagem com o critério de desempate)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed