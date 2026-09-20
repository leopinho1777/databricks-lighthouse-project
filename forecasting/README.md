# Demand Forecasting Workstream

Demand-forecasting analysis for the Lighthouse project, in three phases:

- **Phase 1 — baselines and segmented methods (`01`–`09`):** forecasting unit, horizon and split (tasks 1.1, 1.2,
  1.5); baselines at several grains; demand-pattern classification; intermittent-demand methods (Croston/SBA,
  ADIDA); hierarchical reconciliation; and the 91-day held-static baseline that closes the phase.
- **Stage 2 — feature engineering (`10`):** a pooled fixed-effects panel regression used to test calendar,
  holiday, weather, economic, marketing and inventory features, ending in a frozen feature set.
- **Stage 3 — model comparison (`experiments/`, `11`):** five model families (fixed-effects panel regression,
  Random Forest, XGBoost, Prophet, SARIMA) scored under one shared protocol against the seasonal-naive champion,
  and a final side-by-side report.

Everything here is analysis code, not a deployed job: `fact_demand_daily` is a disposable scratch table, not a
committed dbt model, and nothing in `forecasting/` is part of the ingestion, transformation or orchestration
bundles. See `../CLAUDE.md` for the rest of the project and [`OVERVIEW.md`](OVERVIEW.md) for the full narrative
of what was done, tested, validated and left open across every stage; this file covers what to run.

## Deliverables

1. [`01_data_exploration/01_data_exploration_summary.md`](01_data_exploration/01_data_exploration_summary.md) — what the transformation layer contains: table inventory, `location_type` split, 2020-2021 anomaly check, censored-demand check.
2. [`02_schema_design/02_ideal_schema_proposal.md`](02_schema_design/02_ideal_schema_proposal.md) — the `fact_demand_daily` schema (product x store x day, dense), how it maps back to the marts, and open questions for the team.
3. [`03_granularity_baselines/03_granularity_comparison_report.md`](03_granularity_baselines/03_granularity_comparison_report.md) — Seasonal Naive / Moving Average / SES backtested at daily/weekly/monthly grain, full catalog, with a granularity recommendation.
4. [`04_demand_classification/04_demand_classification_summary.md`](04_demand_classification/04_demand_classification_summary.md) — full-catalog ADI/CV² demand-pattern classification (Smooth/Intermittent/Erratic/Lumpy), routing input for Croston/SBA.
5. [`05_croston_sba/05_croston_sba_summary.md`](05_croston_sba/05_croston_sba_summary.md) — full-catalog Croston/SBA backtest against `03`'s daily baselines, per-series and portfolio-level.
6. [`06_multi_grain/06_multi_grain_summary.md`](06_multi_grain/06_multi_grain_summary.md) — weekly-grain ADI/CV² reclassification and ADIDA (weekly SBA disaggregated to daily) against `05`'s native daily SBA.
7. [`07_hierarchical_reconciliation/stage1_bottom_up/stage1_bottom_up_report.md`](07_hierarchical_reconciliation/stage1_bottom_up/stage1_bottom_up_report.md) — Bottom-Up national forecast (sums `06`'s recommended per-series forecast across all 6 locations), first stage of the Top-Down/Bottom-Up/MinT comparison.
8. [`07_hierarchical_reconciliation/stage2_top_down/stage2_top_down_report.md`](07_hierarchical_reconciliation/stage2_top_down/stage2_top_down_report.md) — Top-Down: national-grain reclassification, routed national forecast, disaggregation to product×location via historical location shares.
9. [`07_hierarchical_reconciliation/stage3_comparison/stage3_comparison_report.md`](07_hierarchical_reconciliation/stage3_comparison/stage3_comparison_report.md) — direct Bottom-Up vs. Top-Down comparison at national and location level; Bottom-Up wins or ties at both, traced to a shared SBA seasonal-lag weakness.
10. [`07_hierarchical_reconciliation/stage4_mint_feasibility/output/mint_feasibility_check.md`](07_hierarchical_reconciliation/stage4_mint_feasibility/output/mint_feasibility_check.md) — MinT feasibility gate: not feasible at either level (holdout periods 2-12% of the rule-of-thumb minimum, covariance matrices exactly singular); Bottom-Up is carried forward.
11. [`07_hierarchical_reconciliation/07_hierarchical_reconciliation_summary.md`](07_hierarchical_reconciliation/07_hierarchical_reconciliation_summary.md) — final summary tying Stages 1-4 back to the classification finding that motivated the workstream.
12. [`08_decision_horizon_and_product_axis/08_decision_horizon_summary.md`](08_decision_horizon_and_product_axis/08_decision_horizon_summary.md) — ADI/CV² classification at monthly grain and along the product axis, error over 15/30-day windows, and aggregate-then-disaggregate against direct per-SKU forecasting; adds WAPE as the cross-level metric.
13. [`09_baseline_close_out/09_baseline_close_out_summary.md`](09_baseline_close_out/09_baseline_close_out_summary.md) — closes Phase 1 (tasks 1.3/1.4/1.6/1.7/1.8): the 91-day held-static Moving Average / Seasonal-Naive baseline, scored across 4 rolling origins with a peak-season split and logged to the `/Shared/00_baseline` MLflow experiment. The Seasonal Naive run is the Stage 3 champion.
14. [`10_feature_engineering/10_frozen_feature_set.md`](10_feature_engineering/10_frozen_feature_set.md) — Stage 2 (tasks 2.1-2.10): pooled fixed-effects panel regression (product x location x week, entity effects + linear trend control) testing calendar, holidays, weather, economic, marketing and internal/inventory features one cumulative addition at a time against a >2% MAPE-improvement threshold, plus a COVID-anomaly check and a weather/calendar multicollinearity check. Only calendar survives into the production feature set (via an accuracy ablation); everything else is not kept, not testable with current data, or a structural control (`trend`). See [`00_feature_backlog.md`](10_feature_engineering/00_feature_backlog.md) for the per-task narrative. Logged to `/Shared/01_feature_iteration`. This is the fixed input for every Stage 3 experiment.
15. [`experiments/README.md`](experiments/README.md) — Stage 3 (tasks 3.1-3.5): the shared evaluation protocol (`experiments/_shared/evaluate.py`) and one folder per model, each with its own `README.md`: [`eva_regression/`](experiments/eva_regression/README.md), [`eros_randomforest/`](experiments/eros_randomforest/README.md), [`gabriel_xgboost/`](experiments/gabriel_xgboost/README.md), [`eros_prophet/`](experiments/eros_prophet/README.md), [`pinho_sarima/`](experiments/pinho_sarima/README.md). Logged to `/Shared/02_model_comparison`.
16. [`11_model_comparison/11_model_comparison_report.md`](11_model_comparison/11_model_comparison_report.md) — Stage 3 close-out (task 3.7): every committed model re-scored side by side against the seasonal-naive champion, with a peak/off-peak split, category-level scores, and the reasons the client's data caps what any of them can do. Logged to `/Shared/02_model_comparison` as `final_comparison_3_7`. It is the input to the team's champion decision (task 3.8).

## Running it

All scripts connect to the live Databricks warehouse using credentials already configured in `~/.dbt/profiles.yml` (the same profile `dbt build` uses); nothing secret is stored in this repo. Requires the `forecasting` dependency group:

```bash
uv sync --dev --group forecasting
```

Then, in order (each stage depends on the previous one's output):

```bash
# 1. Refresh the exploration numbers backing 01_data_exploration_summary.md
uv run python forecasting/01_data_exploration/explore_marts.py

# 2. Build the fact_demand_daily prototype in your scratch schema
uv run python forecasting/02_schema_design/build_prototype.py

# 3. Granularity/baseline backtest off the prototype
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

# 12. Phase 1 close-out: 91-day held-static baseline, walk-forward, peak-season split
uv run python forecasting/09_baseline_close_out/run_genuine_baseline.py

# 13. Log the baseline to the /Shared/00_baseline MLflow experiment
uv run python forecasting/09_baseline_close_out/log_baseline_to_mlflow.py

# 14. Stage 2 feature engineering (tasks 2.1-2.10) -- each script is independently
# runnable and cumulative (it calls the previous task's add_*_features() directly);
# see 10_feature_engineering/00_feature_backlog.md for the per-task order and
# 10_feature_engineering/_shared/panel_regression.py for the shared fixed-effects
# fitting logic every task calls.
uv run python forecasting/10_feature_engineering/02_calendar/add_calendar_features.py
uv run python forecasting/10_feature_engineering/03_holidays/add_holiday_features.py
uv run python forecasting/10_feature_engineering/04_weather/add_weather_features.py
uv run python forecasting/10_feature_engineering/05_economic/add_economic_features.py
uv run python forecasting/10_feature_engineering/06_marketing/add_marketing_features.py
uv run python forecasting/10_feature_engineering/07_internal_inventory/add_inventory_features.py
uv run python forecasting/10_feature_engineering/08_covid_anomaly/analyze_covid_anomaly.py
uv run python forecasting/10_feature_engineering/09_multicollinearity_check/check_multicollinearity.py
uv run python forecasting/10_feature_engineering/run_ablation.py

# 15. Stage 3 experiments (one folder per model; see each folder's README.md for options and runtime)
uv run python forecasting/experiments/eva_regression/run_panel_regression.py            # SMEARING=1 for the smearing run
uv run python forecasting/experiments/eros_randomforest/train_random_forest.py
uv run python forecasting/experiments/gabriel_xgboost/train_xgboost.py
uv run python forecasting/experiments/eros_prophet/pilot_timing.py                      # then:
uv run python forecasting/experiments/eros_prophet/train_prophet.py                     # needs the CmdStan backend
uv run python forecasting/experiments/pinho_sarima/train_sarima.py

# 16. Stage 3 close-out: final model comparison (reads the committed experiment outputs; no refit),
# then log it as one consolidated run to /Shared/02_model_comparison
uv run python forecasting/11_model_comparison/build_comparison.py
uv run python forecasting/11_model_comparison/log_comparison_to_mlflow.py
```

`_shared/db_connection.py` is the shared connection helper all stages use. Large intermediate query-result caches (`output/_*.parquet`) are gitignored; only the small summary CSVs that back the markdown reports are tracked.

## Data source convention

Every script connects as *whoever* is running it (via their own `~/.dbt/profiles.yml` dev profile), and query targets are split by kind of data so results stay comparable across the team:

- **Stable reference data** (`dim_*`, `fct_*`, `stg_*`) is read from the shared prod catalog: `_shared.db_connection.PROD_MARTS` (`lh_nautical.marts`) / `PROD_STAGING` (`lh_nautical.staging`). Every developer reads the same numbers, without re-deriving the same source data into their own dev schema.
- **Disposable scratch/experimental tables** (`fact_demand_daily` and every `10_feature_engineering/` intermediate) are written to each developer's own dev schema via `_shared.db_connection.get_scratch_schema()` (`<catalog>.<dev_schema>_forecasting_scratch`, derived from the same dev profile the connection authenticates with). Run `02_schema_design/build_prototype.py` once per developer to materialize your own copy of `fact_demand_daily` before running `03` onward.

This is a middle ground between reading and writing one shared dev schema (which breaks when that schema's owner rebuilds or revokes access) and fully isolated per-developer copies of everything (which forces redundant full-reload builds and lets the copies drift apart). Production is never written to by this workstream.
