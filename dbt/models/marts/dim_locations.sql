with locations as (
    select
        location_id,
        name,
        location_type,
        city,
        state,
        country,
        is_active
    from {{ ref('stg_locations') }}
)
select * from locations
