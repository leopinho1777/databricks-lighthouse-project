with sales as (

    select * from {{ ref('int_sales_enriched') }}

),

final as (

    select
        -- Fact surrogate key (grain: order line item)
        {{ dbt_utils.generate_surrogate_key(['order_item_id']) }} as sales_sk,

        -- Natural keys
        order_item_id,
        order_id,

        -- Foreign keys for dimensions
        customer_id,
        salesperson_id,
        location_id,
        product_variant_id,

        -- Context attributes for customer dimension
        channel,
        order_status,
        placed_at,

        -- Metrics (for sum)
        quantity,
        unit_price,
        line_total,
        icms_rate,
        ipi_rate

    from sales

)

select * from final
