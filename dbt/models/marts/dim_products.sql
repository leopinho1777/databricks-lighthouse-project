with variants as (

    select
        product_variant_id,
        product_id,
        sku,
        barcode_ean,
        sale_price,
        cost_price,
        icms_rate,
        ipi_rate,
        weight_kg
    from {{ ref('stg_product_variants') }}

),

products as (

    select
        product_id,
        product_name,
        category_name,
        is_categorized,
        brand_id
    from {{ ref('int_products_categorized') }}

),

brands as (

    select
        brand_id,
        brand_name,
        country_code as brand_country
    from {{ ref('stg_brands') }}

),

enriched as (

    select
        v.product_variant_id,
        v.product_id,
        v.sku,
        v.barcode_ean,

        p.product_name,
        p.category_name,
        p.is_categorized,

        b.brand_name,
        b.brand_country,

        v.sale_price,
        v.cost_price,
        v.icms_rate,
        v.ipi_rate,
        v.weight_kg

    from variants as v
    inner join products as p
        on v.product_id = p.product_id
    left join brands as b
        on p.brand_id = b.brand_id

),

final as (

    select
        -- Surrogate key
        {{ dbt_utils.generate_surrogate_key(['product_variant_id']) }} as product_variant_sk,

        -- Natural key
        product_variant_id,
        product_id,

        
        sku,
        barcode_ean,
        product_name,
        category_name,
        is_categorized,
        brand_name,
        brand_country,

        -- Metrics for tax
        sale_price,
        cost_price,
        icms_rate,
        ipi_rate,
        weight_kg

    from enriched

)

select * from final