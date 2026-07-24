with suppliers as (

    select
        supplier_id,
        legal_name,
        trade_name,
        country,
        tax_id_type,
        is_active
    from {{ ref('stg_suppliers') }}

)

select * from suppliers