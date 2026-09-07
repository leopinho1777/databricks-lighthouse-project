# Demand Forecasting — Phase 1 (Baseline Model Definition)

Exploratory workstream for Task 1.1 (forecasting unit/granularity), 1.2 (forecast horizon), and 1.5 (train/val/test split) of the demand-forecasting Action Plan. Everything here is **exploratory and prototype-only** — no ML/regression model is built in this phase, and `fact_demand_daily` is a disposable scratch table, not a committed dbt model. See `../CLAUDE.md` for the rest of the project.

## Deliverables

1. [`01_data_exploration/01_data_exploration_summary.md`](01_data_exploration/01_data_exploration_summary.md) — what the transformation layer actually contains: table inventory, `location_type` split, 2020-2021 anomaly check, censored-demand check.
2. [`02_schema_design/02_ideal_schema_proposal.md`](02_schema_design/02_ideal_schema_proposal.md) — the proposed `fact_demand_daily` schema (product x store x day, dense), how it maps back to the marts, and open questions for the team.
3. [`03_granularity_baselines/03_granularity_comparison_report.md`](03_granularity_baselines/03_granularity_comparison_report.md) — Seasonal Naive / Moving Average / SES backtested at daily/weekly/monthly grain, full catalog, with a granularity recommendation.

## Running it

All three scripts connect to the live Databricks dev warehouse using credentials already configured in `~/.dbt/profiles.yml` (the same profile `dbt build` uses) — nothing secret is stored in this repo. Requires the `forecasting` dependency group:

```bash
uv sync --group forecasting
```

Then, in order (each stage depends on the previous one's output):

```bash
# 1. Refresh the exploration numbers backing 01_data_exploration_summary.md
uv run python forecasting/01_data_exploration/explore_marts.py

# 2. Rebuild the fact_demand_daily prototype in the scratch schema
uv run python forecasting/02_schema_design/build_prototype.py

# 3. Re-run the granularity/baseline backtest off the prototype
uv run python forecasting/03_granularity_baselines/run_baselines.py
```

`_shared/db_connection.py` is the shared connection helper all three use. Large intermediate query-result caches (`output/_*.parquet`) are gitignored — only the small summary CSVs that back the markdown reports are tracked.
