with source as (

    select * from {{ source('bronze', 'customers') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'tax_id',
            'created_at',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        id,
        person_type,
        legal_name,
        trade_name,
        tax_id,
        state_registration,
        email,
        phone,
        is_active,
        created_at,
        updated_at,
        _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed