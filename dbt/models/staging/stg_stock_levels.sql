with source as (

    select 
        *,
        -- Criando a Surrogate Key (ID único) combinando Produto + Local
        md5(concat(cast(product_variant_id as string), '-', cast(location_id as string))) as id
    from {{ source('bronze', 'stock_levels') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'product_variant_id',
            'location_id',
            'updated_at',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as stock_level_id,
        product_variant_id,
        location_id,

        -- Attributes
        cast(quantity_on_hand as integer) as quantity_on_hand,

        -- Timestamps
        cast(updated_at as timestamp) as updated_at,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed