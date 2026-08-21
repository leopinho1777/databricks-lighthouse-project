with sales as (

    select * from {{ ref('int_sales_enriched') }}

),

customers as (

    select
        customer_sk,
        customer_id
    from {{ ref('dim_customers') }}

),

employees as (

    select
        employee_sk,
        employee_id
    from {{ ref('dim_employees') }}

),

locations as (

    select
        location_sk,
        location_id
    from {{ ref('dim_locations') }}

),

products as (

    select
        product_variant_sk,
        product_variant_id
    from {{ ref('dim_products') }}

),

final as (

    select
        -- Fact surrogate key (grain: order line item)
        {{ dbt_utils.generate_surrogate_key(['order_item_id']) }} as sales_sk,

        -- Natural keys
        sales.order_item_id,
        sales.order_id,

        -- Foreign keys for dimensions
        c.customer_sk,
        sales.customer_id,
        e.employee_sk as salesperson_sk,
        sales.salesperson_id,
        l.location_sk,
        sales.location_id,
        p.product_variant_sk,
        sales.product_variant_id,
        coalesce(cast(date_format(sales.placed_at, 'yyyyMMdd') as int), 19000101) as date_id,

        -- Context attributes for customer dimension
        sales.channel,
        sales.order_status,
        sales.placed_at,
        sales.payment_method,

        -- Metrics (for sum)
        sales.quantity,
        sales.unit_price,
        sales.line_total,
        sales.icms_rate,
        sales.ipi_rate

    from sales
    left join customers as c
        on sales.customer_id = c.customer_id
    left join employees as e
        on sales.salesperson_id = e.employee_id
    left join locations as l
        on sales.location_id = l.location_id
    left join products as p
        on sales.product_variant_id = p.product_variant_id

)

select * from final