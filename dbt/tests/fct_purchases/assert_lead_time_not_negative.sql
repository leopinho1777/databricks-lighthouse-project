select
    goods_receipt_item_id,
    po_number,
    placed_at,
    received_at,
    lead_time_days
from {{ ref('fct_purchases') }}
where lead_time_days < 0