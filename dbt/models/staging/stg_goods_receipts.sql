with source as (

    select * from {{ source('bronze', 'goods_receipts') }}

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

    from source

    -- Elimina a duplicação sistemática de 2x capturando o lote mais recente
    qualify row_number() over (
        partition by id 
        order by _ingested_at desc nulls last
    ) = 1

)

select * from renamed