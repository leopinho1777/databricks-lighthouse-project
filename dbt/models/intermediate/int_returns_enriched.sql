-- Model: int_returns_enriched (intermediate)
-- Purpose: One record per returned order item, enriched with its return header context (customer,
--          location, status, reason, etc.). Reusable returns base grain that feeds the returns marts.

with return_items as (

    select
        return_item_id,
        return_id,
        order_item_id,
        exchange_variant_id,
        quantity,
        action,
        unit_refund_amount
    from {{ ref('stg_return_items') }}

),

order_items as (

    select order_item_id, product_variant_id
    from {{ ref('stg_order_items') }}

),

returns as (

    select
        return_id,
        order_id,
        customer_id,
        received_at_location_id,
        return_number,
        status,
        reason,
        created_at
    from {{ ref('stg_returns') }}

),

enriched as (

    select
        -- Grain: a returned item
        ri.return_item_id,
        ri.return_id,

        -- Bridge with original sale + keys for dimensions
        ri.order_item_id,
        oi.product_variant_id,
        r.order_id,
        r.customer_id,
        r.received_at_location_id as location_id,
        ri.exchange_variant_id,

        -- Context of the return
        r.return_number,
        r.status as return_status,
        r.reason,
        ri.action,
        r.created_at as returned_at,

        -- Metrics
        ri.quantity,
        ri.unit_refund_amount,
        ri.quantity * ri.unit_refund_amount as refund_amount

    from return_items as ri
    inner join order_items as oi
        on ri.order_item_id = oi.order_item_id
    inner join returns as r
        on ri.return_id = r.return_id

)

select * from enriched