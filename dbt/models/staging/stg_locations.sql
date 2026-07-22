with source as (

    select * from {{ source('bronze', 'locations') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'name',
            'location_type',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as location_id,

        -- Core Attributes
        trim(name) as name,
        lower(trim(location_type)) as location_type,

        -- Address Details
        trim(postal_code) as postal_code,
        trim(street) as street,
        trim(number) as number,
        trim(complement) as complement,
        trim(district) as district,
        trim(city) as city,

        -- Geopolitics (Padronizando igual a stg_addresses)
        upper(trim(state)) as state,
        upper(trim(country)) as country,

        -- Flags
        cast(is_active as boolean) as is_active,

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