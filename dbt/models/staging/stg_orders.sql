with source as (

    select * from {{ source('bronze', 'orders') }}

),

renamed as (

    select
        -- Keys
        id as order_id,
        customer_id,
        salesperson_id,
        location_id,

        -- Attributes
        order_number,
        channel,
        status,

        -- Measures
        subtotal,
        discount_amount,
        total,

        -- Timestamps
        cast(placed_at as timestamp) as placed_at,
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from source

    -- Pega a última versão que de fato entrou no banco (remove duplicatas)
    qualify row_number() over (
        partition by id 
        order by _ingested_at desc nulls last
    ) = 1

)

select * from renamed