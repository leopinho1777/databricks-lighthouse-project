with customers as (

    select
        customer_id,
        person_type,
        legal_name,
        trade_name,
        tax_id,
        state_registration,
        email,
        phone,
        is_active
    from {{ ref('stg_customers') }}

),

addresses as (

    select
        customer_id,
        city,
        state,
        country
    from {{ ref('stg_addresses') }}
    where is_primary = true

),

final as (

    select
        c.customer_id,
        c.person_type,
        c.legal_name,
        c.trade_name,
        c.tax_id,
        c.state_registration,
        c.email,
        c.phone,
        c.is_active,

        a.city,
        a.state,
        a.country

    from customers as c
    left join addresses as a
        on c.customer_id = a.customer_id

)

select * from final