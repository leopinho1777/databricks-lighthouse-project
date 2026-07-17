with source as (

    select * from {{ source('bronze', 'employees') }}

),

renamed as (

    select
        -- Keys
        id as employee_id,
        primary_location_id,

        -- Attributes
        full_name,
        cpf,
        email,
        role as employee_role,
        is_active as is_active_employee,

        -- Dates (Tipagem explícita de data para análise de tempo de empresa)
        cast(hire_date as date) as hire_date,
        cast(termination_date as date) as termination_date,

        -- Timestamps
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata (Garantindo a linhagem com o critério de desempate)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from source

    -- Remove as duplicatas de 2x escolhendo o lote mais recente de ingestão
    qualify row_number() over (
        partition by id 
        order by _ingested_at desc nulls last
    ) = 1

)

select * from renamed