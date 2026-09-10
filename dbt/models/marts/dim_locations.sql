-- Model: dim_locations (marts)
-- Purpose: Location dimension. Contains historical records for each warehouse or store location (SCD
--          Type 2).

with locations as (
    select
        {{ dbt_utils.generate_surrogate_key(['location_id', 'updated_at']) }} as location_sk,
        location_id,
        name as location_name,
        location_type,
        city as city_name,
        state as state_code,
        country as country_name,
        is_active,
        updated_at
    from {{ ref('stg_locations') }}
)

select * from locations