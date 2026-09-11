-- Test: assert_fct_returns_non_negative_refund
-- Fails if any return has a negative refund amount.
select * from {{ ref('fct_returns') }} where refund_amount < 0