-- Model: stg_suppliers (staging)
-- Purpose: Suppliers and vendor information standardized from bronze.

with source as (

    select * from {{ source('bronze', 'suppliers') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'legal_name',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as supplier_id,

        -- Company Details
        trim(legal_name) as legal_name,
        trim(trade_name) as trade_name,
        upper(trim(country)) as country,
        trim(tax_id) as tax_id,
        upper(trim(tax_id_type)) as tax_id_type,

        -- Contact Info
        lower(trim(email)) as email,
        trim(phone) as phone,
        trim(contact_name) as contact_name,

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