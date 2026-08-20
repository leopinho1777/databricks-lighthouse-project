with purchases as (

    select * from {{ ref('int_purchases_enriched') }}

),

employees as (

    select
        employee_sk,
        employee_id
    from {{ ref('dim_employees') }}

),

products as (

    select
        product_variant_sk,
        product_variant_id
    from {{ ref('dim_products') }}

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['goods_receipt_item_id']) }} as purchases_sk,

        -- Chaves naturais
        purchases.goods_receipt_item_id,
        purchases.goods_receipt_id,
        purchases.purchase_order_item_id,
        purchases.purchase_order_id,

        -- Chaves estrangeiras para dimensões
        purchases.supplier_sk,
        purchases.supplier_id,
        purchases.location_sk,
        purchases.destination_location_id,
        e.employee_sk,
        purchases.employee_id,
        p.product_variant_sk,
        purchases.product_variant_id,

        -- Contexto
        purchases.po_number,
        purchases.purchase_order_status,
        purchases.currency,
        purchases.placed_at,
        purchases.expected_delivery_at,
        purchases.received_by_employee_id,
        purchases.received_at,

        -- Medidas de quantidade
        purchases.quantity_ordered,
        purchases.quantity_received,

        -- Medidas de valor
        purchases.unit_cost,
        purchases.unit_cost_brl,
        purchases.line_total,
        purchases.line_total_brl,

        -- Medidas de prazo
        purchases.lead_time_days,
        purchases.delay_days

    from purchases
    left join employees as e
        on purchases.employee_id = e.employee_id
    left join products as p
        on purchases.product_variant_id = p.product_variant_id

)

select * from final