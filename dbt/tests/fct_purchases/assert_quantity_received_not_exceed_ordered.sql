-- Test: assert_quantity_received_not_exceed_ordered
-- Fails if any goods receipt line received more units than were ordered.

select
    goods_receipt_item_id,
    po_number,
    quantity_ordered,
    quantity_received
from {{ ref('fct_purchases') }}
where quantity_received > quantity_ordered