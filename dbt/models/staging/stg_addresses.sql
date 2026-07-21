with source as (

    select * from {{ source('bronze', 'addresses') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'customer_id',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as address_id,
        customer_id,

        -- Categorical & Standardized
        lower(trim(address_type)) as address_type,
        
        -- Address Details
        trim(postal_code) as postal_code,
        trim(street) as street,
        trim(number) as number,
        trim(complement) as complement,
        trim(district) as district,
        trim(city) as city,
        
        -- Geopolitics (Padronizando para maiúsculas e sem espaços)
        upper(trim(state)) as state,
        upper(trim(country)) as country,

        -- Flags
        cast(is_primary as boolean) as is_primary,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed