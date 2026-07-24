with source as (

    select * from {{ ref('stg_suppliers') }}

),

final as (

    select
        -- Version-Aware Primary Surrogate Key
        {{ dbt_utils.generate_surrogate_key(['supplier_id', 'updated_at']) }} as supplier_sk,
        
        -- Natural Key
        supplier_id,
        
        -- Disambiguated Attributes
        legal_name as supplier_legal_name,
        trade_name as supplier_trade_name,
        country as supplier_country_name,
        tax_id_type,
        is_active,
        
        -- SCD Type 2 Metadata Columns
        updated_at as valid_from,
        lead(updated_at) over (
            partition by supplier_id 
            order by updated_at
        ) as valid_to,
        case 
            when lead(updated_at) over (
                partition by supplier_id 
                order by updated_at
            ) is null then true 
            else false 
        end as is_current
    from source

)

select * from final