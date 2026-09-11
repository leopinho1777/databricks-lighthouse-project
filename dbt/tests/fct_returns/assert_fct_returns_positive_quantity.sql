-- Test: assert_fct_returns_positive_quantity
-- Fails if any return has a zero or negative quantity.
select * from {{ ref('fct_returns') }} where quantity <= 0