with source as (

    select * from {{ source('bronze', 'products') }}

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
            'category_id',
            'brand_id',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as product_id,
        category_id,
        brand_id,

        -- Core Attributes
        trim(name) as product_name,
        coalesce(trim(description), 'Sem descrição informada') as description,
        
        -- Fiscal & Units (initial string cleanup)
        trim(ncm_code) as ncm_code,
        lower(trim(unit_of_measure)) as unit_of_measure,

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