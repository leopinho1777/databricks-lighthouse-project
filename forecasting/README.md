# Demand Forecasting — Phase 1 (Baseline Model Definition) & Phase 2 (Segmented Methods)

Exploratory workstream for Task 1.1 (forecasting unit/granularity), 1.2 (forecast horizon), and 1.5 (train/val/test split) of the demand-forecasting Action Plan, followed by a segmented-treatment phase (classify by demand pattern, apply intermittent-demand methods to the non-smooth segments). Everything here is **exploratory and prototype-only** — no ML/regression model is built in this phase, and `fact_demand_daily` is a disposable scratch table, not a committed dbt model. See `../CLAUDE.md` for the rest of the project. See [`OVERVIEW.md`](OVERVIEW.md) for the full narrative of what was done, tested, validated, and left open across every stage below — this file only covers what to run.

## Deliverables

1. [`01_data_exploration/01_data_exploration_summary.md`](01_data_exploration/01_data_exploration_summary.md) — what the transformation layer actually contains: table inventory, `location_type` split, 2020-2021 anomaly check, censored-demand check.
2. [`02_schema_design/02_ideal_schema_proposal.md`](02_schema_design/02_ideal_schema_proposal.md) — the proposed `fact_demand_daily` schema (product x store x day, dense), how it maps back to the marts, and open questions for the team.
3. [`03_granularity_baselines/03_granularity_comparison_report.md`](03_granularity_baselines/03_granularity_comparison_report.md) — Seasonal Naive / Moving Average / SES backtested at daily/weekly/monthly grain, full catalog, with a granularity recommendation.
4. [`04_demand_classification/04_demand_classification_summary.md`](04_demand_classification/04_demand_classification_summary.md) — full-catalog ADI/CV² demand-pattern classification (Smooth/Intermittent/Erratic/Lumpy), routing input for Croston/SBA treatment.
5. [`05_croston_sba/05_croston_sba_summary.md`](05_croston_sba/05_croston_sba_summary.md) — full-catalog Croston/SBA backtest vs. `03`'s daily baselines, per-series and portfolio-level.
6. [`06_multi_grain/06_multi_grain_summary.md`](06_multi_grain/06_multi_grain_summary.md) — weekly-grain ADI/CV² reclassification and ADIDA (weekly SBA disaggregated to daily) vs. `05`'s native daily SBA.
7. [`07_hierarchical_reconciliation/stage1_bottom_up/stage1_bottom_up_report.md`](07_hierarchical_reconciliation/stage1_bottom_up/stage1_bottom_up_report.md) — Bottom-Up national forecast (sums `06`'s recommended per-series forecast across all 6 locations), first stage of the Top-Down/Bottom-Up/MinT reconciliation comparison.
8. [`07_hierarchical_reconciliation/stage2_top_down/stage2_top_down_report.md`](07_hierarchical_reconciliation/stage2_top_down/stage2_top_down_report.md) — Top-Down: national-grain reclassification, routed national forecast, disaggregation to product×location via historical location shares.
9. [`07_hierarchical_reconciliation/stage3_comparison/stage3_comparison_report.md`](07_hierarchical_reconciliation/stage3_comparison/stage3_comparison_report.md) — direct Bottom-Up vs. Top-Down comparison at national and location level; Bottom-Up wins/ties at both, traced to a shared SBA seasonal-lag weakness rather than a genuine information-content trade-off.
10. [`07_hierarchical_reconciliation/stage4_mint_feasibility/output/mint_feasibility_check.md`](07_hierarchical_reconciliation/stage4_mint_feasibility/output/mint_feasibility_check.md) — MinT feasibility gate: not feasible at either level (holdout periods 2-12% of the rule-of-thumb minimum, covariance matrices exactly singular); recommends Bottom-Up per Stage 3 instead.
11. [`07_hierarchical_reconciliation/07_hierarchical_reconciliation_summary.md`](07_hierarchical_reconciliation/07_hierarchical_reconciliation_summary.md) — final summary tying Stages 1-4 back to the classification finding that motivated the workstream, with a carry-forward recommendation.
12. [`08_decision_horizon_and_product_axis/08_decision_horizon_summary.md`](08_decision_horizon_and_product_axis/08_decision_horizon_summary.md) — ADI/CV² classification at monthly grain and along the product axis, error measured over the 15/30-day decision horizon instead of per day, and aggregate-then-disaggregate (category and `product_id`) vs. direct per-SKU forecasting; adds WAPE as the cross-level metric.
13. [`09_baseline_close_out/09_baseline_close_out_summary.md`](09_baseline_close_out/09_baseline_close_out_summary.md) — closes Phase 1 (tasks 1.3/1.4/1.6/1.7/1.8): a genuine 91-day held-static Moving Average/Seasonal-Naive baseline (fixes `08`'s still-continuously-refreshed windows), scored across 4 rolling origins with a peak-season split, logged to the `/Shared/00_baseline` MLflow experiment.

## Running it

All scripts connect to the live Databricks dev warehouse using credentials already configured in `~/.dbt/profiles.yml` (the same profile `dbt build` uses) — nothing secret is stored in this repo. Requires the `forecasting` dependency group:

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

# 4. Classify every series by demand pattern (ADI/CV²) off the same prototype
uv run python forecasting/04_demand_classification/classify_demand_patterns.py

# 5. Croston/SBA backtest, full catalog, benchmarked against 03's daily baselines
uv run python forecasting/05_croston_sba/run_croston_sba.py

# 6. Weekly reclassification + ADIDA (weekly SBA disaggregated to daily) vs. 05's native daily SBA
uv run python forecasting/06_multi_grain/run_multi_grain.py

# 7. Hierarchical reconciliation, Stage 1: Bottom-Up national forecast (sums 06's per-series output)
uv run python forecasting/07_hierarchical_reconciliation/stage1_bottom_up/run_stage1_bottom_up.py

# 8. Hierarchical reconciliation, Stage 2: Top-Down national forecast + location-share disaggregation
uv run python forecasting/07_hierarchical_reconciliation/stage2_top_down/run_stage2_top_down.py

# 9. Hierarchical reconciliation, Stage 3: Bottom-Up vs. Top-Down comparison (national + location)
uv run python forecasting/07_hierarchical_reconciliation/stage3_comparison/run_stage3_comparison.py

# 10. Hierarchical reconciliation, Stage 4: MinT feasibility check
uv run python forecasting/07_hierarchical_reconciliation/stage4_mint_feasibility/run_stage4_mint_feasibility.py

# 11. Decision-horizon evaluation and product-axis aggregation tests
uv run python forecasting/08_decision_horizon_and_product_axis/run_decision_horizon.py

# 12. Phase 1 close-out: genuine 91-day held-static baseline, walk-forward, peak-season split
uv run python forecasting/09_baseline_close_out/run_genuine_baseline.py

# 13. Log the corrected baseline to the /Shared/00_baseline MLflow experiment
uv run python forecasting/09_baseline_close_out/log_baseline_to_mlflow.py
```

`_shared/db_connection.py` is the shared connection helper all stages use. Large intermediate query-result caches (`output/_*.parquet`) are gitignored — only the small summary CSVs that back the markdown reports are tracked.
