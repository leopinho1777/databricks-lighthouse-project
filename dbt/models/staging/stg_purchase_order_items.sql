with source as (

    select * from {{ source('bronze', 'purchase_order_items') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'purchase_order_id',
            'product_variant_id',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as purchase_order_item_id,
        purchase_order_id,
        product_variant_id,

        -- Attributes
        cast(quantity_ordered as integer) as quantity_ordered,

        -- Amounts
        cast(unit_cost as decimal(18, 2)) as unit_cost,
        cast(line_total as decimal(18, 2)) as line_total,

        -- Metadata
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed