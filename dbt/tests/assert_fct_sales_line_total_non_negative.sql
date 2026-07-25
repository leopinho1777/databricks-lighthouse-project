select *
from {{ ref('fct_sales') }}
where line_total < 0