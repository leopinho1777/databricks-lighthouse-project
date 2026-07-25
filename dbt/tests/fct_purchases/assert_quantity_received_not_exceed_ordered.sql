select
    goods_receipt_item_id,
    po_number,
    quantity_ordered,
    quantity_received
from {{ ref('fct_purchases') }}
where quantity_received > quantity_ordered