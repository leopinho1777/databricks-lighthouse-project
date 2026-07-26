with employees as (

    select
        employee_id,
        location_id,
        full_name,
        employee_role,
        hire_date,
        is_active_employee
    from {{ ref('stg_employees') }}

),

final as (

    select
        -- Surrogate Key
        {{ dbt_utils.generate_surrogate_key(['employee_id']) }} as employee_sk,

        -- Natural keys
        employee_id,

        -- Attributes
        full_name,
        employee_role,
        location_id,
        hire_date,
        is_active_employee

    from employees

)

select * from final