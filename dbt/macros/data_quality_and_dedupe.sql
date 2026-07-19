-- Keep latest valid ingestion

{% macro dedupe_latest(
    relation_name, 
    partition_by, 
    order_by="_ingested_at desc nulls last, _batch_id desc nulls last") %}
select *
from {{ relation_name }}
qualify row_number() over (
    partition by {{ partition_by }}
    order by {{ order_by }}
) = 1
{% endmacro %}

{% macro keep_required_rows(relation_name, required_columns) %}
select *
from {{ relation_name }}
where 1 = 1
{% for column_name in required_columns %}
  and {{ column_name }} is not null
{% endfor %}
{% endmacro %}