-- Model: agg_customer_monthly (marts)
-- Purpose: Monthly aggregate table at the customer grain (Customer x Month). Built using a date spine
--          cross-join to ensure every month since the customer's first purchase is represented, even
--          if they made no purchases (zero-filled). Ideal for cohort analysis, Monthly Recurring
--          Revenue (MRR), and MoM retention charts.

with fct_sales as (

    select
        customer_id,
        order_id,
        line_total,
        placed_at,
        order_status
    from {{ ref('fct_sales') }}

),

customers as (

    select
        customer_id,
        person_type
    from {{ ref('dim_customers') }}

),

calendary as (

    select distinct
        month_start
    from {{ ref('dim_calendary') }}
    -- Filter out future months to avoid empty rows in the BI
    where month_start <= trunc(current_date(), 'MM')
      and year > 1900 and year > 1900 -- Removes the dummy date (1900-01-01)

),

customer_first_purchase as (

    -- Find when each customer's "lifetime" starts, so no zero-filled months exist before it
    select 
        customer_id,
        min(trunc(cast(placed_at as date), 'MM')) as first_active_month
    from fct_sales
    where order_status in ('paid', 'confirmed') -- Valid revenue only
    group by 1

),

customer_spine as (

    -- Build the full grid: customer x every month since their first purchase
    select
        c.customer_id,
        c.person_type,
        cal.month_start as reporting_month
    from customer_first_purchase as cfp
    left join customers as c 
        on cfp.customer_id = c.customer_id
    cross join calendary as cal
    where cal.month_start >= cfp.first_active_month

),

sales_monthly_aggs as (

    -- Aggregate the customer's actual sales month by month
    select
        customer_id,
        trunc(cast(placed_at as date), 'MM') as active_month,
        count(distinct order_id) as total_valid_orders,
        sum(line_total) as monthly_revenue,
        max(placed_at) as last_purchase_at
    from fct_sales
    where order_status in ('paid', 'confirmed') -- Valid revenue only
    group by 1, 2

),

final as (

    -- Join the grid with actual sales; COALESCE fills months with no sales with zero
    select
        {{ dbt_utils.generate_surrogate_key(['spine.customer_id', 'spine.reporting_month']) }} as customer_monthly_sk,
        spine.customer_id,
        spine.person_type,
        spine.reporting_month,
        coalesce(sales.total_valid_orders, 0) as total_valid_orders,
        coalesce(sales.monthly_revenue, 0) as monthly_revenue,
        sales.last_purchase_at
    from customer_spine as spine
    left join sales_monthly_aggs as sales
        on spine.customer_id = sales.customer_id
        and spine.reporting_month = sales.active_month

)

select * from final