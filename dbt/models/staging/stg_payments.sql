with source as (

    select * from {{ source('bronze', 'payments') }}

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
            'amount',
            'paid_at',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as payment_id,
        order_id,

        -- Attributes
        method as payment_method,
        status as payment_status,

        -- Measures
        installments,
        amount,

        -- Timestamps (Tipagem explícita para os testes de macro)
        cast(paid_at as timestamp) as paid_at,
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata (Garantindo a linhagem com o critério de desempate)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed