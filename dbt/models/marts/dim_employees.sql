with employees as (

    select
        id as employee_id,
        full_name,
        role,
        primary_location_id,
        hire_date,
        termination_date,
        is_active
    from {{ ref('stg_employees') }}

)

select * from employees