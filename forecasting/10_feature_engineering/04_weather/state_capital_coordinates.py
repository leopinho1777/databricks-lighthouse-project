# %%
"""Brazilian state-capital lat/lon lookup used as a weather proxy for each
`dim_locations` row.

`dim_locations.city_name` in this project's dev data is Faker-generated mock
data (city names like "Barbosa do Sul", "Cavalcanti da Mata" don't correspond
to real, geocodable Brazilian cities -- see root CLAUDE.md: "this is a mock
database intended for learning purposes"). `state_code` IS real, though, so
rather than geocoding fictional city names, this maps each real Brazilian
state code to its capital's coordinates as the nearest reasonable weather
proxy. Only the states actually present in `dim_locations` need an entry;
extend this table if new states appear.
"""

STATE_CAPITAL_COORDINATES = {
    "PR": {"capital": "Curitiba", "lat": -25.4284, "lon": -49.2733},
    "AP": {"capital": "Macapa", "lat": 0.0389, "lon": -51.0664},
    "PI": {"capital": "Teresina", "lat": -5.0892, "lon": -42.8016},
    "AL": {"capital": "Maceio", "lat": -9.6498, "lon": -35.7089},
}
