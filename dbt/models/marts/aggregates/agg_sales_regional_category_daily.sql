-- Model: agg_sales_regional_category_daily (marts)
-- Purpose: Daily sales aggregation at the Region (State) and Product Category grain. Designed
--          specifically to support geographical and categorical filtering in BI dashboards without
--          hitting the detailed fact table. Excludes order counts to prevent fan-out
--          (double-counting) issues for multi-category orders.

with fct_sales as (

    select
        date_id,
        channel,
        customer_sk,
        product_variant_sk,
        quantity,
        line_total
    from {{ ref('fct_sales') }}
    where order_status in ('paid', 'confirmed') -- Only real income

),

customers as (

    select
        customer_sk,
        coalesce(state, 'Não Informado') as customer_state
    from {{ ref('dim_customers') }}

),

products as (

    select
        product_variant_sk,
        category_name
    from {{ ref('dim_products') }}

),

joined as (

    select
        s.date_id,
        s.channel,
        c.customer_state,
        p.category_name,
        s.quantity,
        s.line_total
    from fct_sales as s
    left join customers as c
        on s.customer_sk = c.customer_sk
    left join products as p
        on s.product_variant_sk = p.product_variant_sk

),

aggs as (

    -- Aggregate by date, channel, customer state and product category
    select
        date_id,
        channel,
        customer_state,
        category_name,
        sum(quantity) as daily_items_sold,
        sum(line_total) as daily_gross_revenue
    from joined
    group by 1, 2, 3, 4

),

final as (

    select
        -- Replacement key (grain: date + channel + customer state + product category)
        {{ dbt_utils.generate_surrogate_key(['date_id', 'channel', 'customer_state', 'category_name']) }} as agg_sk,
        date_id,
        channel,
        customer_state,
        category_name,
        daily_items_sold,
        daily_gross_revenue
    from aggs

)

select * from final