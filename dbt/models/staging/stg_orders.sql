with source as (

select * from {{ source('bronze', 'orders') }}

),

deduplicated as (

{{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

{{ keep_required_rows(
'deduplicated',
        [
'id',
'customer_id',
'location_id',
'placed_at',
'total',
'_ingested_at',
'_source_origin',
'_batch_id'
        ]
    ) }}

),

renamed as (

select
-- Keys
        id as order_id,
        customer_id,
        salesperson_id,
        location_id,

-- Attributes
        order_number,
        channel,
        status,

-- Measures
        subtotal,
        discount_amount,
        total,

-- Timestamps
cast(placed_at as timestamp) as placed_at,
cast(created_at as timestamp) as created_at,
cast(updated_at as timestamp) as updated_at,

-- Metadata
cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

from cleaned_required

)

-- Exclude orders with future-placed_at dates — mock data contains future-dated rows that should not reach marts
select * from renamed
where placed_at <= current_timestamp()