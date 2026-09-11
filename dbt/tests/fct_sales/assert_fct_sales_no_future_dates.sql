-- Test: assert_fct_sales_no_future_dates
-- Fails if any order in fct_sales is placed in the future (placed_at later than now).

select
    order_item_id,
    order_id,
    placed_at
from {{ ref('fct_sales') }}
where placed_at > current_timestamp()
