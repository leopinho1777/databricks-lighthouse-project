-- Model: stg_employees (staging)
-- Purpose: Employee master data standardized from bronze.

with source as (

    select * from {{ source('bronze', 'employees') }}

),

deduplicated as (

    {{ dedupe_latest('source', 'id') }}

),

cleaned_required as (

    {{ keep_required_rows(
        'deduplicated',
        [
            'id',
            'primary_location_id',
            'hire_date',
            '_ingested_at',
            '_source_origin',
            '_batch_id'
        ]
    ) }}

),

renamed as (

    select
        -- Keys
        id as employee_id,
        primary_location_id as location_id,

        -- Attributes
        full_name,
        cpf,
        email,
        role as employee_role,
        is_active as is_active_employee,

        -- Dates (explicit date typing for tenure analysis)
        cast(hire_date as date) as hire_date,
        cast(termination_date as date) as termination_date,

        -- Timestamps
        cast(created_at as timestamp) as created_at,
        cast(updated_at as timestamp) as updated_at,

        -- Metadata (keeps lineage with the tie-breaker criterion)
        cast(_ingested_at as timestamp) as _ingested_at,
        _source_origin,
        _batch_id

    from cleaned_required

)

select * from renamed