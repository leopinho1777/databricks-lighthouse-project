with employees as (

    select
        employee_id,
        full_name,
        employee_role,
        location_id,
        hire_date,
        termination_date,
        is_active_employee
    from {{ ref('stg_employees') }}

)

select * from employees