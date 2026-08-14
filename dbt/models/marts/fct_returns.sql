with returns as (

    select * from {{ ref('int_returns_enriched') }}

),

customers as (

    select
        customer_sk,
        customer_id
    from {{ ref('dim_customers') }}

),

locations as (

    select
        location_sk,
        location_id
    from {{ ref('dim_locations') }}

),

products as (

    select
        product_sk,
        product_variant_id
    from {{ ref('dim_products') }}

),

final as (

    select
        -- Replacement key (grain: returned item)
        {{ dbt_utils.generate_surrogate_key(['return_item_id']) }} as return_sk,

        -- Natural / degenerate keys
        returns.return_item_id,
        returns.return_id,
        returns.return_number,

        -- Bridge with sale + keys to the dimensions
        returns.order_item_id,
        returns.order_id,
        c.customer_sk,
        returns.customer_id,
        l.location_sk,
        returns.location_id,
        p.product_sk,
        returns.exchange_variant_id,

        -- Context attributes
        returns.return_status,
        returns.reason,
        returns.action,
        returns.returned_at,

        -- Metrics
        returns.quantity,
        returns.unit_refund_amount,
        returns.refund_amount

    from returns
    left join customers as c
        on returns.customer_id = c.customer_id
    left join locations as l
        on returns.location_id = l.location_id
    left join products as p
        on returns.exchange_variant_id = p.product_variant_id

)

select * from final