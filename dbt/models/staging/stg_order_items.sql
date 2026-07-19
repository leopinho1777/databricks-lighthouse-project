with source as (

    select * from {{ source('bronze', 'order_items') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'order_id',
            'product_variant_id',
            'quantity',
            'line_total',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Chaves (IDs) com cast explícito para garantir a integridade dos JOINs
        cast(id as string) as order_item_id,
        cast(order_id as string) as order_id,
        cast(product_variant_id as string) as product_variant_id,
        
        -- Métricas de Quantidade e Valores
        cast(quantity as int) as quantity,
        cast(unit_price as decimal(18, 2)) as unit_price,
        cast(line_total as decimal(18, 2)) as line_total,
        
        -- Impostos (Convertendo taxas para decimais padronizados se necessário)
        cast(icms_rate as decimal(5, 2)) as icms_rate,
        cast(ipi_rate as decimal(5, 2)) as ipi_rate,
        
        -- Metadados de Auditoria
        cast(_ingested_at as timestamp) as ingested_at,
        cast(_source_origin as string) as source_origin,
        cast(_batch_id as string) as batch_id

    from cleaned_required

)

select * from renamed