-- Model: agg_sales_regional_orders_daily (marts)
-- Purpose: Daily order count aggregation at the Region (State) and Channel grain. Built separately
--          from the category aggregate to avoid fan-out (double-counting) of orders that contain
--          items from multiple categories.

with fct_sales as (

    select
        date_id,
        channel,
        customer_sk,
        order_id
    from {{ ref('fct_sales') }}
    where order_status in ('paid', 'confirmed') -- Only valid orders

),

customers as (

    select
        customer_sk,
        coalesce(state, 'Não Informado') as customer_state
    from {{ ref('dim_customers') }}

),

joined as (

    select
        s.date_id,
        s.channel,
        c.customer_state,
        s.order_id
    from fct_sales as s
    left join customers as c
        on s.customer_sk = c.customer_sk

),

aggs as (

    -- Grouping without the category and perform a distinct count of the order.
    select
        date_id,
        channel,
        customer_state,
        count(distinct order_id) as daily_valid_orders
    from joined
    group by 1, 2, 3

),

final as (

    select
        -- Replacement key (grain: date + channel + customer state)
        {{ dbt_utils.generate_surrogate_key(['date_id', 'channel', 'customer_state']) }} as agg_sk,
        date_id,
        channel,
        customer_state,
        daily_valid_orders
    from aggs

)

select * from final