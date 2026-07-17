with goods_receipts as (

    select
        goods_receipt_id,
        purchase_order_id,
        received_at
    from {{ ref('stg_goods_receipts') }}

),

purchase_orders as (

    select
        purchase_order_id,
        supplier_id,
        po_number,
        expected_delivery_at
    from {{ ref('stg_purchase_orders') }}

),

joined as (

    select
        gr.goods_receipt_id,
        po.purchase_order_id,
        po.supplier_id,
        po.po_number,
        po.expected_delivery_at,
        gr.received_at,

        -- Custom macro: whole-day difference between expected and received
        {{ days_between('po.expected_delivery_at', 'gr.received_at') }} as delivery_delay_days

    from goods_receipts as gr
    inner join purchase_orders as po
        on gr.purchase_order_id = po.purchase_order_id

),

final as (

    select
        *,
        case
            when expected_delivery_at is null or received_at is null then 'unknown'
            when delivery_delay_days > 0 then 'late'
            when delivery_delay_days < 0 then 'early'
            else 'on_time'
        end as delivery_status
    from joined

)

select * from final