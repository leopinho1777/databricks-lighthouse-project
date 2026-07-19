{% macro _row_loss_counts_query(source_table_name, partition_by, required_columns) %}
with source as (
    select * from {{ source('bronze', source_table_name) }}
),

deduplicated as (
    {{ dedupe_latest('source', partition_by) }}
),

cleaned_required as (
    {{ keep_required_rows('deduplicated', required_columns) }}
)

select
    (select count(*) from source) as source_rows,
    (select count(*) from deduplicated) as deduplicated_rows,
    (select count(*) from cleaned_required) as cleaned_required_rows,
    (select count(*) from source) - (select count(*) from deduplicated) as dropped_by_dedupe,
    (select count(*) from deduplicated) - (select count(*) from cleaned_required) as dropped_by_required,
    (select count(*) from source) - (select count(*) from cleaned_required) as dropped_total,
    case
        when (select count(*) from source) = 0 then 0.00
        else round(
            100.0 * (
                ((select count(*) from source) - (select count(*) from deduplicated))
                / cast((select count(*) from source) as double)
            ),
            2
        )
    end as dedupe_loss_pct,
    case
        when (select count(*) from deduplicated) = 0 then 0.00
        else round(
            100.0 * (
                ((select count(*) from deduplicated) - (select count(*) from cleaned_required))
                / cast((select count(*) from deduplicated) as double)
            ),
            2
        )
    end as required_loss_pct,
    case
        when (select count(*) from source) = 0 then 0.00
        else round(
            100.0 * (
                ((select count(*) from source) - (select count(*) from cleaned_required))
                / cast((select count(*) from source) as double)
            ),
            2
        )
    end as total_loss_pct
{% endmacro %}

{% macro report_row_loss_for_model(model_name, source_table_name, partition_by, required_columns) %}
    {% set sql %}
        {{ _row_loss_counts_query(source_table_name, partition_by, required_columns) }}
    {% endset %}

    {% set result = run_query(sql) %}

    {% if execute %}
        {% set source_rows = result.columns[0].values()[0] %}
        {% set deduplicated_rows = result.columns[1].values()[0] %}
        {% set cleaned_required_rows = result.columns[2].values()[0] %}
        {% set dropped_by_dedupe = result.columns[3].values()[0] %}
        {% set dropped_by_required = result.columns[4].values()[0] %}
        {% set dropped_total = result.columns[5].values()[0] %}
        {% set dedupe_loss_pct = result.columns[6].values()[0] %}
        {% set required_loss_pct = result.columns[7].values()[0] %}
        {% set total_loss_pct = result.columns[8].values()[0] %}

        {{ log(
            model_name
            ~ ' | source=' ~ source_rows
            ~ ' | dedup=' ~ deduplicated_rows
            ~ ' | required=' ~ cleaned_required_rows
            ~ ' | drop_dedup=' ~ dropped_by_dedupe
            ~ ' | drop_required=' ~ dropped_by_required
            ~ ' | drop_total=' ~ dropped_total
            ~ ' | dedupe_loss_pct=' ~ dedupe_loss_pct
            ~ ' | required_loss_pct=' ~ required_loss_pct
            ~ ' | total_loss_pct=' ~ total_loss_pct,
            info=True
        ) }}
    {% endif %}
{% endmacro %}

{% macro ensure_row_loss_audit_table() %}
    {% set sql %}
        create table if not exists {{ target.database }}.{{ target.schema }}._staging_row_loss_audit (
            model_name string,
            source_rows bigint,
            deduplicated_rows bigint,
            cleaned_required_rows bigint,
            dropped_by_dedupe bigint,
            dropped_by_required bigint,
            dropped_total bigint,
            dedupe_loss_pct double,
            required_loss_pct double,
            total_loss_pct double,
            run_started_at timestamp,
            recorded_at timestamp
        ) using delta
    {% endset %}

    {% do run_query(sql) %}
{% endmacro %}

{% macro persist_row_loss_for_model(model_name, source_table_name, partition_by, required_columns) %}
    {% set metrics_sql %}
        {{ _row_loss_counts_query(source_table_name, partition_by, required_columns) }}
    {% endset %}

    {% set insert_sql %}
        insert into {{ target.database }}.{{ target.schema }}._staging_row_loss_audit
        select
            '{{ model_name }}' as model_name,
            source_rows,
            deduplicated_rows,
            cleaned_required_rows,
            dropped_by_dedupe,
            dropped_by_required,
            dropped_total,
            dedupe_loss_pct,
            required_loss_pct,
            total_loss_pct,
            cast('{{ run_started_at }}' as timestamp) as run_started_at,
            current_timestamp() as recorded_at
        from (
            {{ metrics_sql }}
        ) m
    {% endset %}

    {% do run_query(insert_sql) %}
{% endmacro %}

{% macro report_row_loss_for_all_staging() %}
    {{ log('Row-loss report start', info=True) }}

    {{ report_row_loss_for_model(
        'stg_customers',
        'customers',
        'id',
        ['id', 'tax_id', 'created_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_employees',
        'employees',
        'id',
        ['id', 'primary_location_id', 'hire_date', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_fiscal_invoices',
        'fiscal_invoices',
        'id',
        ['id', 'order_id', 'total_amount', 'issued_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_goods_receipts',
        'goods_receipts',
        'id',
        ['id', 'purchase_order_id', 'received_by_employee_id', 'received_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_order_items',
        'order_items',
        'id',
        ['id', 'order_id', 'product_variant_id', 'quantity', 'line_total', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_orders',
        'orders',
        'id',
        ['id', 'customer_id', 'location_id', 'placed_at', 'total', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_payments',
        'payments',
        'id',
        ['id', 'order_id', 'amount', 'paid_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_purchase_orders',
        'purchase_orders',
        'id',
        ['id', 'supplier_id', 'buyer_id', 'destination_location_id', 'placed_at', 'expected_delivery_at', 'total', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ report_row_loss_for_model(
        'stg_stock_movements',
        'stock_movements',
        'id',
        ['id', 'product_variant_id', 'location_id', 'occurred_at', 'quantity', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ log('Row-loss report end', info=True) }}
{% endmacro %}

{% macro persist_row_loss_for_all_staging() %}
    {{ ensure_row_loss_audit_table() }}
    {{ log('Row-loss persistence start', info=True) }}

    {{ persist_row_loss_for_model(
        'stg_customers',
        'customers',
        'id',
        ['id', 'tax_id', 'created_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_employees',
        'employees',
        'id',
        ['id', 'primary_location_id', 'hire_date', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_fiscal_invoices',
        'fiscal_invoices',
        'id',
        ['id', 'order_id', 'total_amount', 'issued_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_goods_receipts',
        'goods_receipts',
        'id',
        ['id', 'purchase_order_id', 'received_by_employee_id', 'received_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_order_items',
        'order_items',
        'id',
        ['id', 'order_id', 'product_variant_id', 'quantity', 'line_total', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_orders',
        'orders',
        'id',
        ['id', 'customer_id', 'location_id', 'placed_at', 'total', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_payments',
        'payments',
        'id',
        ['id', 'order_id', 'amount', 'paid_at', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_purchase_orders',
        'purchase_orders',
        'id',
        ['id', 'supplier_id', 'buyer_id', 'destination_location_id', 'placed_at', 'expected_delivery_at', 'total', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ persist_row_loss_for_model(
        'stg_stock_movements',
        'stock_movements',
        'id',
        ['id', 'product_variant_id', 'location_id', 'occurred_at', 'quantity', '_ingested_at', '_source_origin', '_batch_id']
    ) }}

    {{ log('Row-loss persistence end', info=True) }}
{% endmacro %}
