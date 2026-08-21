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
        product_variant_sk,
        product_variant_id
    from {{ ref('dim_products') }}

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['returns.return_item_id']) }} as return_sk,

        returns.return_item_id,
        returns.return_id,
        returns.return_number,

        returns.order_item_id,
        returns.order_id,
        c.customer_sk,
        returns.customer_id,
        l.location_sk,
        returns.location_id,
        
        -- Correct returned product, resolved directly from dim_products
        p.product_variant_sk,
        returns.product_variant_id as returned_variant_id,
        
        returns.exchange_variant_id,

        returns.return_status,
        returns.reason,
        returns.action,
        
        -- Clean cast while filtering with WHERE clause below
        cast(date_format(returns.returned_at, 'yyyyMMdd') as int) as date_id,
        returns.returned_at,

        returns.quantity,
        returns.unit_refund_amount,
        returns.refund_amount

    from returns
    left join customers as c
        on returns.customer_id = c.customer_id
    left join locations as l
        on returns.location_id = l.location_id
        
    -- INNER JOIN filters out returns whose product variant has no dimension row.
    inner join products as p
        on returns.product_variant_id = p.product_variant_id
        
    -- WHERE filters out date anomalies (null or in the future)
    where returns.returned_at is not null
      and cast(returns.returned_at as date) <= current_date()

)

select * from final