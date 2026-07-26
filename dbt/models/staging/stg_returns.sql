with source as (

    select * from {{ source('bronze', 'returns') }}

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
            'created_at',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as return_id,
        order_id,
        customer_id,
        received_at_location_id,

        -- Attributes
        return_number,
        status,
        case
            when lower(reason) like '%desist%'                            then 'Cliente desistiu da compra'
            when lower(reason) like '%duplicad%'                          then 'Compra duplicada'
            when lower(reason) like '%descriç%' or lower(reason) like '%corresspond%' then 'Item não corresponde à descrição'
            when lower(reason) like '%transporte%' or lower(reason) like '%variado%'   then 'Produto avariado no transporte'
            when lower(reason) like '%tamanho%' or lower(reason) like '%cor%'          then 'Tamanho/cor incorretos'
            when lower(reason) like '%defeito%'                           then 'Produto com defeito de fábrica'
            else 'Motivo não definido'
        end as reason,

        -- Amounts
        cast(total_refund_amount as decimal(18, 2)) as total_refund_amount,

        -- Timestamps
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed