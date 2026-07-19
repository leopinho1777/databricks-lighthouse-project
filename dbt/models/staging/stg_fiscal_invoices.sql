with source as (

    select * from {{ source('bronze', 'fiscal_invoices') }}

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
            'total_amount',
            'issued_at',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

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

    from cleaned_required

)

select * from renamed