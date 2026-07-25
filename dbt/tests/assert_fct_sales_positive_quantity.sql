select *
from {{ ref('fct_sales') }}
where quantity <= 0