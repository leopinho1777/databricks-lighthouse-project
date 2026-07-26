-- Falha se alguma devolução tiver reembolso negativo.
select * from {{ ref('fct_returns') }} where refund_amount < 0