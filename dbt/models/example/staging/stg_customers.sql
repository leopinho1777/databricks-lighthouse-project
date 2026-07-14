with source as (

    select * from {{ source('bronze', 'customers') }}

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

    from source

)

select * from renamed