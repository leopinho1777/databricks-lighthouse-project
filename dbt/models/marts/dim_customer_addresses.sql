with source as (
    select * from {{ ref('stg_addresses') }}
),

final as (
    select
        -- Version-aware surrogate key for the address history record
        {{ dbt_utils.generate_surrogate_key(['customer_id', 'address_id', '_ingested_at']) }} as customer_address_sk,

        -- Natural keys
        customer_id,
        address_id,
        address_type,

        -- Address attributes
        is_primary,
        postal_code,
        street,
        number,
        complement,
        district,
        city,
        state,
        country,

        -- Ingestion-based SCD2 timestamps
        _ingested_at as valid_from,

        -- SCD2 metadata
        lead(_ingested_at) over (
            partition by customer_id, address_id
            order by _ingested_at
        ) as valid_to,
        case
            when lead(_ingested_at) over (
                partition by customer_id, address_id
                order by _ingested_at
            ) is null then true
            else false
        end as is_current
    from source
)

select * from final
