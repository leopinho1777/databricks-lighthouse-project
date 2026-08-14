with fct_sales as (

    select * from {{ ref('fct_sales') }}

),

customers as (

    select 
        customer_id,
        person_type
    from {{ ref('dim_customers') }}

),

customer_aggs as (

    select
        -- Table grain: Customer
        customer_id,
        
        -- Temporal metrics
        min(cast(placed_at as date)) as first_purchase_date,
        max(cast(placed_at as date)) as last_purchase_date,
        
        -- Volume metrics
        count(distinct 
            case 
                when order_status != 'canceled' then order_id 
            end
        ) as total_valid_orders,
        
        -- Lifetime Value (Gross Revenue proxy for ABC classification)
        sum(
            case 
                when order_status != 'canceled' then line_total 
                else 0 
            end
        ) as lifetime_gross_revenue

    from fct_sales
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

        -- Churn Risk metrics (Decision D6: 18 months / ~540 days)
        datediff(current_date(), ca.last_purchase_date) as days_since_last_purchase,
        
        case 
            when datediff(current_date(), ca.last_purchase_date) > 540 then true 
            else false 
        end as is_churn_risk,
        
        -- Window functions for ABC Curve calculation
        sum(ca.lifetime_gross_revenue) over (
            order by ca.lifetime_gross_revenue desc
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
        
        -- ABC Classification (Decision D7: Class A = Top 80% Revenue)
        case
            when running_revenue / total_revenue <= 0.80 then 'A'
            when running_revenue / total_revenue <= 0.95 then 'B'
            else 'C'
        end as abc_class

    from customer_behavior

)

select * from final