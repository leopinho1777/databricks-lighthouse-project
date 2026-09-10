-- Test: assert_fct_sales_positive_quantity
-- Fails if any sales line has a zero or negative quantity.

select *
from {{ ref('fct_sales') }}
where quantity <= 0