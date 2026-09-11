-- Test: assert_lead_time_not_negative
-- Fails if any purchase has a negative lead time (received before it was ordered).

select
    goods_receipt_item_id,
    po_number,
    placed_at,
    received_at,
    lead_time_days
from {{ ref('fct_purchases') }}
where lead_time_days < 0