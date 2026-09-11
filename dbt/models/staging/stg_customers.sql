-- Model: stg_customers (staging)
-- Purpose: Customer master data standardized from bronze.

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
        -- Keys
        id as customer_id,

        -- Attributes
        person_type,
        legal_name,
        trade_name,
        tax_id,
        state_registration,
        email,
        phone,
        is_active,

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