-- Model: stg_product_variants (staging)
-- Purpose: Product variants (SKUs, pricing, weight and tax rates) standardized from bronze.

with source as (

    select * from {{ source('bronze', 'product_variants') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'product_id',
            'sku',
            'sale_price',
            'cost_price',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as product_variant_id,
        product_id,

        -- Standardized Identifiers
        upper(trim(sku)) as sku,
        trim(barcode_ean) as barcode_ean,

        -- Financials & Measures
        cast(sale_price as decimal(16, 2)) as sale_price,
        cast(cost_price as decimal(16, 2)) as cost_price,
        cast(weight_kg as decimal(10, 3)) as weight_kg,

        -- Tax Rates (cast to decimal(10, 4) to avoid overflow)
        cast(icms_rate as decimal(10, 4)) as icms_rate,
        cast(ipi_rate as decimal(10, 4)) as ipi_rate,

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