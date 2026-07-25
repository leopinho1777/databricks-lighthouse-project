with goods_receipt_items as (

    select
        goods_receipt_item_id,
        goods_receipt_id,
        purchase_order_item_id,
        quantity_received
    from {{ ref('stg_goods_receipt_items') }}

),

purchase_order_items as (

    select
        purchase_order_item_id,
        purchase_order_id,
        product_variant_id,
        quantity_ordered,
        unit_cost,
        line_total
    from {{ ref('stg_purchase_order_items') }}

),

purchase_orders as (

    select
        purchase_order_id,
        supplier_id,
        buyer_id,
        destination_location_id,
        po_number,
        purchase_order_status,
        currency,
        placed_at,
        expected_delivery_at
    from {{ ref('stg_purchase_orders') }}

),

goods_receipts as (

    select
        goods_receipt_id,
        purchase_order_id,
        received_by_employee_id,
        received_at
    from {{ ref('stg_goods_receipts') }}

),

exchange_rates as (

    select
        exchange_date,
        currency_from,
        exchange_rate
    from {{ ref('stg_exchange_rates') }}
    where currency_to = 'BRL'

),

-- Grão: 1 item recebido
base as (

    select
        gri.goods_receipt_item_id,
        gri.goods_receipt_id,
        gri.purchase_order_item_id,
        gri.quantity_received,

        poi.purchase_order_id,
        poi.product_variant_id,
        poi.quantity_ordered,
        poi.unit_cost,
        poi.line_total,

        po.supplier_id,
        po.buyer_id,
        po.destination_location_id,
        po.po_number,
        po.purchase_order_status,
        po.currency,
        po.placed_at,
        po.expected_delivery_at,

        gr.received_by_employee_id,
        gr.received_at

    from goods_receipt_items as gri
    inner join purchase_order_items as poi
        on gri.purchase_order_item_id = poi.purchase_order_item_id
    inner join purchase_orders as po
        on poi.purchase_order_id = po.purchase_order_id
    inner join goods_receipts as gr
        on gri.goods_receipt_id = gr.goods_receipt_id

),

-- Join direto: dim_suppliers não possui múltiplas versões reais por supplier_id
supplier_at_purchase as (

    select
        b.goods_receipt_item_id,
        s.supplier_sk
    from base as b
    inner join {{ ref('dim_suppliers') }} as s
        on b.supplier_id = s.supplier_id

),

-- Join direto: dim_locations não possui múltiplas versões reais por location_id
location_at_purchase as (

    select
        b.goods_receipt_item_id,
        l.location_sk
    from base as b
    inner join {{ ref('dim_locations') }} as l
        on b.destination_location_id = l.location_id

),

-- Taxa de câmbio vigente na data do pedido
converted as (

    select
        b.goods_receipt_item_id,
        b.currency,
        b.unit_cost,
        b.line_total,
        er.exchange_rate,

        {{ convert_currency('b.unit_cost', 'b.currency', 'er.exchange_rate') }} as unit_cost_brl,
        {{ convert_currency('b.line_total', 'b.currency', 'er.exchange_rate') }} as line_total_brl

    from base as b
    left join exchange_rates as er
        on b.currency = er.currency_from
        and cast(b.placed_at as date) = er.exchange_date

),

enriched as (

    select
        b.goods_receipt_item_id,
        b.goods_receipt_id,
        b.purchase_order_item_id,
        b.purchase_order_id,

        -- Chaves para dimensões
        sp.supplier_sk,
        lp.location_sk,
        b.buyer_id as employee_id,
        b.product_variant_id,

        -- Contexto
        b.po_number,
        b.purchase_order_status,
        b.currency,
        b.placed_at,
        b.expected_delivery_at,
        b.received_by_employee_id,
        b.received_at,

        -- Medidas de quantidade
        b.quantity_ordered,
        b.quantity_received,

        -- Medidas de valor (originais e convertidas)
        c.unit_cost,
        c.unit_cost_brl,
        c.line_total,
        c.line_total_brl,

        -- Medidas de prazo
        {{ days_between('b.placed_at', 'b.received_at') }} as lead_time_days,
        {{ days_between('b.expected_delivery_at', 'b.received_at') }} as delay_days

    from base as b
    left join supplier_at_purchase as sp
        on b.goods_receipt_item_id = sp.goods_receipt_item_id
    left join location_at_purchase as lp
        on b.goods_receipt_item_id = lp.goods_receipt_item_id
    left join converted as c
        on b.goods_receipt_item_id = c.goods_receipt_item_id

)

select * from enriched