with source as (

    select * from {{ source('bronze', 'stock_movements') }}

),

renamed as (

    select
        -- Keys
        id as stock_movement_id,
        product_variant_id,
        location_id,
        employee_id,
        reference_id,

        -- Attributes
        movement_type,
        reference_table,
        notes,

        -- Measures
        quantity,

        -- Timestamps (Essencial para análise histórica de estoque)
        cast(occurred_at as timestamp) as occurred_at,
        cast(created_at as timestamp) as created_at,

        -- Metadata (Garantindo a linhagem com o critério de desempate)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from source

    -- Remove as duplicatas de 2x escolhendo o lote mais recente de ingestão
    qualify row_number() over (
        partition by id 
        order by _ingested_at desc nulls last
    ) = 1

)

select * from renamed