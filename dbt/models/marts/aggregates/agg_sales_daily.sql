-- Model: agg_sales_daily (marts)
-- Purpose: Aggregate table with daily sales metrics by channel. Contains gross revenue, returned
--          amounts, taxes applied to the residual amount, net revenue, and order volumes. Grain: 1
--          row per Day (date_id) and Channel (channel).

with fct_sales as (

    select * from {{ ref('fct_sales') }}

),

returns as (

    -- Fan-out prevention: aggregate returns per item before the JOIN
    select
        order_item_id,
        sum(refund_amount) as refund_amount
    from {{ ref('int_returns_enriched') }}
    group by 1

),

daily_metrics as (

    select
        -- Table grain: Day and Channel
        s.date_id,
        s.channel,
        
        -- Gross Revenue (valid orders only: 'paid' and 'confirmed')
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then s.line_total 
                else 0 
            end
        ) as gross_revenue,

        -- Returned Amount (Abated in the original sale month)
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then coalesce(r.refund_amount, 0) 
                else 0 
            end
        ) as returned_amount,

        -- Total Taxes (ICMS + IPI applied only to the retained amount)
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then 
                    (s.line_total - coalesce(r.refund_amount, 0)) * ((coalesce(s.icms_rate, 0) + coalesce(s.ipi_rate, 0)) / 100.0)
                else 0 
            end
        ) as total_taxes,

        -- Net Revenue (Retained amount minus taxes)
        sum(
            case 
                when s.order_status in ('paid', 'confirmed') then 
                    (s.line_total - coalesce(r.refund_amount, 0)) - 
                    ((s.line_total - coalesce(r.refund_amount, 0)) * ((coalesce(s.icms_rate, 0) + coalesce(s.ipi_rate, 0)) / 100.0))
                else 0 
            end
        ) as net_revenue,
        
        -- Valid Orders Volume
        count(distinct 
            case 
                when s.order_status in ('paid', 'confirmed') then s.order_id 
            end
        ) as valid_orders_volume,
        
        -- Canceled Orders Volume (For Cancellation Rate)
        count(distinct 
            case 
                when s.order_status = 'cancelled' then s.order_id 
            end
        ) as canceled_orders_volume,

        -- Total Items Volume (For Average Basket Size)
        count(
            case 
                when s.order_status in ('paid', 'confirmed') then s.order_item_id 
            end
        ) as valid_items_volume

    from fct_sales as s
    left join returns as r
        on s.order_item_id = r.order_item_id
    group by 1, 2

)

select * from daily_metrics