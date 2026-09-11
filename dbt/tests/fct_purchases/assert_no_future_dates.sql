-- expected_delivery_at is intentionally excluded: it's a planned/scheduled date and
-- legitimately forward-looking (see filter_future_dated.sql), unlike placed_at.
select
    goods_receipt_item_id,
    po_number,
    placed_at,
    expected_delivery_at
from {{ ref('fct_purchases') }}
where placed_at > current_timestamp()