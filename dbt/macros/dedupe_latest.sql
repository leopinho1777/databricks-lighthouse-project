-- Keep latest valid ingestion

{% macro dedupe_latest(
    relation_name, 
    partition_by, 
    order_by="_ingested_at desc nulls last") %}
select *
from {{ relation_name }}
qualify row_number() over (
    partition by {{ partition_by }}
    order by {{ order_by }}
) = 1
{% endmacro %}