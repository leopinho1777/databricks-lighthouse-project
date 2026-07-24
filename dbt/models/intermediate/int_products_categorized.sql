with products as (

    select
        product_id,
        product_name,
        category_id,
        brand_id
    from {{ ref('stg_products') }}

),

category_fix as (

    select
        product_type,
        correct_category,
        is_categorized
    from {{ ref('seed_category_fix') }}

),

typed as (

    select
        product_id,
        product_name,
        brand_id,

        -- Extracts the "type": removes the number from the end of the name ("Motor de Popa 1540" -> "Motor de Popa")
        trim(regexp_replace(product_name, '\\s*\\d+\\s*$', '')) as product_type

    from products

),

categorized as (

    select
        t.product_id,
        t.product_name,
        t.product_type,
        t.brand_id,

        -- Category corrected via seed; fallback protects new/unknown types
        coalesce(cf.correct_category, 'Não Classificado') as category_name,
        coalesce(cf.is_categorized, false)                as is_categorized

    from typed as t
    left join category_fix as cf
        on t.product_type = cf.product_type

)

select * from categorized