with order_items as (

    select
        order_item_id,
        order_id,
        product_variant_id,
        quantity,
        unit_price,
        line_total,
        icms_rate,
        ipi_rate
    from {{ ref('stg_order_items') }}

),

orders as (

    select
        order_id,
        customer_id,
        salesperson_id,
        location_id,
        channel,
        status,
        placed_at
    from {{ ref('stg_orders') }}

),

-- Deduplicate payments to get the primary method per order (highest amount)
payments as (

    select 
        order_id, 
        payment_method
    from (
        select 
            order_id, 
            payment_method,
            row_number() over (partition by order_id order by amount desc) as rn
        from {{ ref('stg_payments') }}
    )
    where rn = 1

),

enriched as (

    select
        -- Grain: Order line item
        oi.order_item_id,
        oi.order_id,

        -- Keys for future dimensions
        o.customer_id,
        o.salesperson_id,
        o.location_id,
        oi.product_variant_id,

        -- Context of order
        o.channel,
        o.status as order_status,
        o.placed_at,
        p.payment_method,

        -- Metrics (for sum)
        oi.quantity,
        oi.unit_price,
        oi.line_total,
        oi.icms_rate,
        oi.ipi_rate

    from order_items as oi
    inner join orders as o
        on oi.order_id = o.order_id
    left join payments as p
        on o.order_id = p.order_id

)

select * from enriched