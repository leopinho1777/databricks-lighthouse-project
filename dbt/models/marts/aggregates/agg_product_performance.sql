with fct_sales as (

    select * from {{ ref('fct_sales') }}

),

returns as (

    -- Fan-out prevention: aggregate returns per item before the JOIN
    select
        order_item_id,
        sum(quantity) as returned_quantity,
        sum(refund_amount) as refund_amount
    from {{ ref('int_returns_enriched') }}
    group by 1

),

products as (

    select
        product_variant_id,
        cost_price,
        product_name,
        category_name,
        brand_name
    from {{ ref('dim_products') }}

),

monthly_aggs as (

    select
        -- Table grain: Month and Product
        cast(date_trunc('month', s.placed_at) as date) as performance_month,
        s.product_variant_id,
        
        -- Product Context
        p.product_name,
        p.category_name,
        p.brand_name,

        -- Volumes
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then s.quantity 
                else 0 
            end
        ) as gross_quantity_sold,
        
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then coalesce(r.returned_quantity, 0) 
                else 0 
            end
        ) as returned_quantity,

        -- Revenues
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then s.line_total 
                else 0 
            end
        ) as gross_revenue,
        
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then coalesce(r.refund_amount, 0) 
                else 0 
            end
        ) as returned_amount,

        -- Taxes (Applied to the residual amount and divided by 100 to fix percentage)
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then
                    (s.line_total - coalesce(r.refund_amount, 0)) * ((coalesce(s.icms_rate, 0) + coalesce(s.ipi_rate, 0)) / 100.0)
                else 0 
            end
        ) as total_taxes,

        -- Cost of Goods Sold (CMV: Net quantity * Standard Cost)
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then
                    (s.quantity - coalesce(r.returned_quantity, 0)) * coalesce(p.cost_price, 0)
                else 0 
            end
        ) as total_cogs

    from fct_sales as s
    left join returns as r
        on s.order_item_id = r.order_item_id
    left join products as p
        on s.product_variant_id = p.product_variant_id
    group by 1, 2, 3, 4, 5

),

final as (

    select
        performance_month,
        product_variant_id,
        product_name,
        category_name,
        brand_name,
        
        -- Calculated Metrics
        gross_quantity_sold,
        returned_quantity,
        (gross_quantity_sold - returned_quantity) as net_quantity_sold,
        
        gross_revenue,
        returned_amount,
        total_taxes,
        total_cogs,
        
        (gross_revenue - returned_amount - total_taxes) as net_revenue,
        
        -- Contribution Margin (Real Profit)
        (gross_revenue - returned_amount - total_taxes - total_cogs) as contribution_margin

    from monthly_aggs

)

select * from final