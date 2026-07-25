select
    goods_receipt_item_id,
    po_number,
    placed_at,
    expected_delivery_at
from {{ ref('fct_purchases') }}
where placed_at > current_timestamp()
   or expected_delivery_at > current_timestamp()