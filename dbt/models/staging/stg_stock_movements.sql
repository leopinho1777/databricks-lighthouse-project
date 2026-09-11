with source as (

    select * from {{ source('bronze', 'stock_movements') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'product_variant_id',
            'location_id',
            'occurred_at',
            'quantity',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as stock_movement_id,
        product_variant_id,
        location_id,
        employee_id,
        reference_id,

        -- Attributes
        lower(trim(movement_type)) as movement_type,
        reference_table,
        notes,

        -- Measures
        case
            when lower(trim(movement_type)) in ('purchase_in', 'return_in') then abs(cast(quantity as integer))
            when lower(trim(movement_type)) in ('sale_out', 'return_out') then -abs(cast(quantity as integer))
            else abs(cast(quantity as integer))
        end as quantity,
        cast(quantity as integer) = 0 as is_zero_quantity_movement,

        -- Timestamps (Essencial para análise histórica de estoque)
        cast(occurred_at as timestamp) as occurred_at,
        cast(created_at as timestamp) as created_at,

        -- Metadata (Garantindo a linhagem com o critério de desempate)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

-- Exclude rows with a future occurred_at — mock data contains future-dated rows that should not reach marts
select * from renamed
where {{ filter_future_dated('occurred_at') }}