-- Model: agg_customer_metrics (marts)
-- Purpose: Aggregate table with historical customer metrics. Calculates gross and net Lifetime Value
--          (LTV), first and last purchase dates, churn risk (segmented thresholds by person_type: 180
--          days for PJ, 240 days for PF), and dynamic ABC Curve classification based on revenue
--          concentration. Grain: 1 row per customer.

with fct_sales as (

    select * from {{ ref('fct_sales') }}

),

customers as (

    select
        customer_id,
        person_type
    from {{ ref('dim_customers') }}

),

returns as (

    -- Fan-out prevention: aggregate returns per item before the JOIN
    select
        order_item_id,
        sum(refund_amount) as refund_amount
    from {{ ref('int_returns_enriched') }}
    group by 1

),

customer_aggs as (

    select
        -- Table grain: Customer
        s.customer_id,

        -- Temporal metrics
        min(cast(s.placed_at as date)) as first_purchase_date,
        max(cast(s.placed_at as date)) as last_purchase_date,

        -- Volume metrics
        count(distinct
            case
                when s.order_status in ('paid', 'confirmed') then s.order_id
            end
        ) as total_valid_orders,

        -- Lifetime Value (Gross Revenue proxy for ABC classification)
        sum(
            case
                when s.order_status in ('paid', 'confirmed') then s.line_total
                else 0
            end
        ) as lifetime_gross_revenue,

        -- Returned Amount (Abated in the original sale)
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
        ) as total_taxes

    from fct_sales as s
    left join returns as r
        on s.order_item_id = r.order_item_id
    group by 1

),

customer_behavior as (

    select
        ca.*,
        c.person_type,
        
        -- Proxy for Purchase Reason (Decision L1: PJ = Professional Use, PF = Leisure)
        case 
            when c.person_type = 'PJ' then 'Professional Use'
            else 'Leisure'
        end as inferred_purchase_reason,

        -- Churn Risk metrics, segmented by person_type (PJ reorders faster/more predictably than PF)
        datediff(current_date(), ca.last_purchase_date) as days_since_last_purchase,

        case
            when c.person_type = 'PJ' and datediff(current_date(), ca.last_purchase_date) > 180 then true
            when c.person_type != 'PJ' and datediff(current_date(), ca.last_purchase_date) > 240 then true
            else false
        end as is_churn_risk,

        -- Net Revenue (Gross minus returns and taxes, for profit-based LTV analysis)
        ca.lifetime_gross_revenue - ca.returned_amount - ca.total_taxes as lifetime_net_revenue,

        -- Window functions for ABC Curve calculation
        -- customer_id as tie-breaker keeps the running total deterministic across runs
        sum(ca.lifetime_gross_revenue) over (
            order by ca.lifetime_gross_revenue desc, ca.customer_id
        ) as running_revenue,
        
        sum(ca.lifetime_gross_revenue) over () as total_revenue

    from customer_aggs as ca
    left join customers as c 
        on ca.customer_id = c.customer_id
    where ca.lifetime_gross_revenue > 0

),

final as (

    select
        customer_id,
        person_type,
        inferred_purchase_reason,
        first_purchase_date,
        last_purchase_date,
        days_since_last_purchase,
        is_churn_risk,
        total_valid_orders,
        lifetime_gross_revenue,
        returned_amount,
        total_taxes,
        lifetime_net_revenue,

        -- ABC Classification (Decision D7: Class A = Top 80% Revenue)
        case
            when running_revenue / total_revenue <= 0.80 then 'A'
            when running_revenue / total_revenue <= 0.95 then 'B'
            else 'C'
        end as abc_class

    from customer_behavior

)

select * from final