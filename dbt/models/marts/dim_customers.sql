with customers as (

    select
        customer_id,
        person_type,
        legal_name,
        trade_name,
        tax_id,
        state_registration,
        is_active
    from {{ ref('stg_customers') }}

),


primary_address as (

    select
        customer_id,
        city,
        state,
        country
    from {{ ref('dim_customer_addresses') }}
    where is_primary = true
      and is_current = true
    -- Guarantees one address per customer even if more than one is flagged "primary"
    qualify row_number() over (partition by customer_id order by address_id) = 1

),

enriched as (

    select
        c.customer_id,
        c.person_type,
        c.legal_name,
        c.trade_name,
        c.tax_id,
        c.state_registration,
        c.is_active,

        a.city,
        a.state,
        a.country

    from customers as c
    left join primary_address as a
        on c.customer_id = a.customer_id

),

final as (

    select
        -- Surrogate key (grain: customer)
        {{ dbt_utils.generate_surrogate_key(['customer_id']) }} as customer_sk,

        -- Natural key
        customer_id,

        -- Customer attributes
        person_type,
        legal_name,
        trade_name,
        tax_id,
        state_registration,
        is_active,

        -- Primary address geography
        city,
        state,
        country

    from enriched

)

select * from final