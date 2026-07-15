with source as (

    select * from {{ source('bronze', 'fiscal_invoices') }}

),

renamed as (

    select
        -- Keys
        id as fiscal_invoice_id,
        order_id,

        -- Attributes
        nfe_number,
        nfe_access_key,
        series,
        status as nfe_status,
        xml_storage_uri,

        -- Measures
        total_amount,

        -- Timestamps (Tipagem explícita para os testes de data)
        cast(issued_at as timestamp) as issued_at,
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata (Garantindo a integridade dos metadados)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from source

    -- Remove as duplicatas de 2x garantindo o registro mais recente
    qualify row_number() over (
        partition by id 
        order by _ingested_at desc nulls last
    ) = 1

)

select * from renamed