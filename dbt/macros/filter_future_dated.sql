-- Filters out rows whose event timestamp is in the future. This project's source
-- data is a mock/synthetic dataset that sometimes contains future-dated rows
-- (originally handled ad hoc in stg_orders.sql) — any column representing "when
-- this happened" must never legitimately be in the future. Do NOT apply to
-- columns that are inherently forward-looking by design (e.g. a scheduled/
-- expected delivery date) — filtering those would incorrectly drop legitimate rows.
-- Works for both DATE and TIMESTAMP typed columns (Spark SQL compares a DATE
-- against current_timestamp() at that date's midnight instant).
--
-- Usage — as a WHERE-clause fragment in a staging model's final select:
--   select * from renamed
--   where {{ filter_future_dated('updated_at') }}
--
-- Combine with other conditions using `and`:
--   where {{ filter_future_dated('occurred_at') }}
--     and some_other_condition
{% macro filter_future_dated(column_name) %}
{{ column_name }} <= current_timestamp()
{% endmacro %}

-- Generic test pairing filter_future_dated(): asserts no row in `model` has a
-- future-dated `column_name`. Apply to any column the macro above filters on, so
-- a regression (e.g. a future ingestion reintroducing future-dated rows) fails
-- `dbt build` automatically instead of being caught by hand again.
--
-- Usage — in a staging model's .yml:
--   - name: updated_at
--     data_tests:
--       - no_future_dates
{% test no_future_dates(model, column_name) %}
select *
from {{ model }}
where {{ column_name }} > current_timestamp()
{% endtest %}
