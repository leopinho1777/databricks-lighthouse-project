-- Falha se alguma devolução tiver quantidade zero ou negativa.
select * from {{ ref('fct_returns') }} where quantity <= 0