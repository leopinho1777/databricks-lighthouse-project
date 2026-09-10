-- Test: assert_fct_sales_line_total_non_negative
-- Fails if any sales line has a negative line_total.

select *
from {{ ref('fct_sales') }}
where line_total < 0