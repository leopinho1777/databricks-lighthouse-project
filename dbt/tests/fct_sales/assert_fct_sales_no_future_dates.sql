-- Assert no future-dated orders in fct_sales (placed_at must be in the past or present)
select
    order_item_id,
    order_id,
    placed_at
from {{ ref('fct_sales') }}
where placed_at > current_timestamp()
