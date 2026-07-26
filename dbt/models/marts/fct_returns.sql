with returns as (

    select * from {{ ref('int_returns_enriched') }}

),

final as (

    select
        -- Replacement key (grain: returned item)
        {{ dbt_utils.generate_surrogate_key(['return_item_id']) }} as return_sk,

        -- Natural / degenerate keys
        return_item_id,
        return_id,
        return_number,

        -- Bridge with sale + keys to the dimensions
        order_item_id,
        order_id,
        customer_id,
        location_id,
        exchange_variant_id,

        -- Context attributes
        return_status,
        reason,
        action,
        returned_at,

        -- Metrics
        quantity,
        unit_refund_amount,
        refund_amount

    from returns

)

select * from final