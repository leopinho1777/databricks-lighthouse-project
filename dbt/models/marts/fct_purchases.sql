with purchases as (

    select * from {{ ref('int_purchases_enriched') }}

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['goods_receipt_item_id']) }} as purchases_sk,

        -- Chaves naturais
        goods_receipt_item_id,
        goods_receipt_id,
        purchase_order_item_id,
        purchase_order_id,

        -- Chaves estrangeiras para dimensões
        supplier_sk,
        location_sk,
        employee_id,
        product_variant_id,

        -- Contexto
        po_number,
        purchase_order_status,
        currency,
        placed_at,
        expected_delivery_at,
        received_by_employee_id,
        received_at,

        -- Medidas de quantidade
        quantity_ordered,
        quantity_received,

        -- Medidas de valor
        unit_cost,
        unit_cost_brl,
        line_total,
        line_total_brl,

        -- Medidas de prazo
        lead_time_days,
        delay_days

    from purchases

)

select * from final