# XGBoost (task 3.3)

One global `XGBRegressor` (all ~6,054 product × location series pooled, not one model per series) that
predicts the **total quantity sold over the next 91 days** in a single shot. Hyperparameters are found with
Hyperopt (30 TPE evaluations) on a validation fold that lies strictly before the four official cutoffs, then the
model is scored under the shared Stage 3 protocol (`../_shared/evaluate.py`) and logged to the
`/Shared/02_model_comparison` MLflow experiment as `xgboost_v1`.

**Result:** the only Stage 3 model that beats the `seasonal_naive_genuine_91d_v2` champion in any window: 1 of
4 (2024-12-31, by 1.75 pp). It loses badly on 2025-04-01 and 2025-07-01. It has the lowest per-series RMSE and
bias of the trained models. `month` carries 64.7% of its importance, which is the main open question about how
well it generalizes.

## Design

- **Single global model.** `period_sufficiency_check.csv`
  (`07_hierarchical_reconciliation/stage4_mint_feasibility`) shows each series has only about a year of usable
  daily history, far too little to fit a model per series. Product and location enter as feature columns.
- **Single-shot 91-day target.** The target is the sum over origin+1 … origin+91, the same aggregate the
  champion is scored on, so WAPE is directly comparable. It also avoids recursive forecasting: a day-by-day model
  would have to feed its own predictions back in as lags to reach day 91, compounding error.
- **Daily grain.** The protocol lets each model fit at its own grain. Daily keeps the lag and rolling features
  at native resolution instead of losing information to a weekly rollup. The panel is dense and zero-filled from
  2020-01-01 (`DENSE_START`), pulled once from `fct_sales` (orders in `paid`/`confirmed` status) in the shared
  prod marts and vectorized with cumulative sums across the whole wide panel.
- **Inputs (`FEATURE_COLS`).**

  | Group | Columns | Origin |
  |---|---|---|
  | Frozen feature set | `month` (a categorical, handled natively; not dummy-encoded), `trend` (days since `DENSE_START`, an explicit structural control because trees have no native trend) | `10_feature_engineering/10_frozen_feature_set.md` |
  | Autoregressive history | `trailing_qty_7d`, `trailing_qty_28d`, `trailing_qty_91d`, `same_period_last_year_qty`, `rolling_std_28d`, `nonzero_days_trailing_91d` | This model's own inputs (built only from data ≤ origin) |
  | Other | `day_of_week`, `demand_category` (ADI/CV² segment label from `04_demand_classification`), `product_variant_id`, `location_id` | This model's own inputs |

  Holiday, weather, economic and marketing covariates are not used: they were tested in Stage 2 and not kept.
  The frozen set governs covariates; the history features, entity keys and segment label are part of this
  model's own design (see the scope note in `10_frozen_feature_set.md`). `demand_category` is a direct input
  here, not only a post-hoc diagnostic as in Random Forest.
- **Training and scoring dates.**
  - Training origins start at 2021-04-01 (`TRAIN_ORIGIN_START`, which leaves 456 days of history before the first
    origin for the longest trailing window plus the year-ago feature), stepped every 30 days on purpose
    (`ORIGIN_STEP_DAYS`). Overlapping origins give the model many rows per series.
  - **Hyperparameter search:** trained on origins whose target window ends by the validation cutoff, validated at
    `TUNE_CUTOFF = 2024-06-30`, whose 91-day target ends 2024-09-29, strictly before the first official cutoff. The
    official numbers never select the model.
  - **Final model:** refit once on all origins whose target window ends on or before 2024-12-31 (including the
    tuning period), with the locked hyperparameters.
  - **Scoring:** the final model is applied at each of the four official cutoffs (2024-12-31, 2025-04-01,
    2025-07-01, 2025-09-30), with features computed from data up to that cutoff. **It is not refit per window**,
    which the protocol asks of models that fit weekly; the four windows are therefore scored by a model that has
    not seen data after 2024-12-31. No future data enters a window's features or fit, but a per-cutoff refit
    (which would also let `trend` and the seasonal shape adapt) is untested and may change the later windows.
- **Reproducibility.** Data snapshot: the committed run logged Delta version 5 of the `fct_sales` it read, and the scored-window totals equal `lh_nautical.marts.fct_sales` exactly (46,163 / 23,216 / 17,354 / 41,435 units); xgboost 3.4.1, hyperopt 0.3.0, pandas 2.3.3,
  numpy 1.26.4, mlflow 3.16.0, logged as tags. The Hyperopt search runs `Trials()` locally, not `SparkTrials()`,
  because the scripts talk to the SQL warehouse through `databricks-sql-connector` rather than running on a Spark
  cluster. MAPE/sMAPE are excluded from all reporting, per `05_croston_sba`.

## Running it

```bash
uv sync --dev --group forecasting
bash forecasting/experiments/gabriel_xgboost/run.sh
# or: uv run --group forecasting python forecasting/experiments/gabriel_xgboost/train_xgboost.py
```

The script builds the feature table, runs the Hyperopt search as nested MLflow runs under a parent
`xgboost_hyperparam_search` run, refits the final model, scores it, and logs `xgboost_v1`. Outputs in `output/`:
`xgboost_v1_window_totals.csv` (input to `../../11_model_comparison`), `_peak_window_totals.csv`,
`_compare_to_baseline.csv`, `_feature_importance.csv`, `_segment_summary.csv`, and `xgboost_best_params.json`.

Selected hyperparameters:

```
max_depth=10, learning_rate=0.0235, n_estimators=100, subsample=0.999,
colsample_bytree=0.853, min_child_weight=4, reg_alpha=7.48, reg_lambda=2.92
```

`n_estimators=100` is the floor of the searched range (100–800) and `reg_alpha=7.48` is near the top of its range
(0.0001–10): a fairly heavily regularized model.

## Results

Portfolio WAPE (%) at SKU × location, all 6,054 series (lower is better). The actual totals are exact 91-day
windows, so they differ from the baseline's by 0.5–1.7% (production actuals have moved slightly since the
baseline was computed):

| Cutoff | Actual units | WAPE (XGBoost) | WAPE (champion) | Delta (pp) | Beats champion |
|---|---|---|---|---|---|
| 2024-12-31 | 46,163 | 77.09 | 78.84 | −1.75 | **Yes** |
| 2025-04-01 | 23,216 | 104.83 | 84.43 | +20.40 | No |
| 2025-07-01 | 17,354 | 124.60 | 88.05 | +36.55 | No |
| 2025-09-30 | 41,435 | 81.47 | 79.89 | +1.57 | No |

Per-segment (a post-hoc join with `demand_category`; bias = actual − forecast, positive means under-forecast):

| Segment | RMSE | Bias |
|---|---|---|
| Intermittent | 5.72 | 1.27 |
| Lumpy | 4.77 | 0.46 |

Both are lower than Random Forest's best configuration (`depth10`: Intermittent 6.44 / 3.48, Lumpy 5.05 / 2.46),
though the two are not perfectly comparable (different grain and feature set).

Feature importance (final model):

| Feature | Importance |
|---|---|
| `month` | 64.7% |
| `trend` | 10.0% |
| `product_variant_id` | 9.7% |
| `demand_category` | 3.5% |
| `day_of_week` | 2.7% |
| `location_id` | 2.1% |
| six history features combined | 7.0% (1.1–1.3% each) |

## Interpretation

- XGBoost targets the mean of raw counts, so it does not have the median-forecast under-forecast of the log-target
  models: its portfolio under-forecast is about 20% against 60–70% for those. Part of its advantage over the
  other experiments is the target choice, not the algorithm.
- The two windows that hurt (2025-04-01 and 2025-07-01) are the same ones that hurt Random Forest most. They are
  the low-volume season (17–23k units against 41–46k). The error there is dispersion, not aggregate bias: on
  2025-07-01 the forecast total is within 2% of actual (bias −1.7%) yet WAPE is 124.6%, because forecast mass is
  spread over series that then sell nothing (25–59% of series sell nothing in a 91-day window, and about 8–10k
  forecast units land on them in each window).
- `month` at 64.7% while the six history features together hold 7.0% means the model leans on "which calendar
  month does the window start in" far more than on recent sales. Plausible explanations, not yet separated:
  genuine seasonality dominance (consistent with this catalog's documented peak season); a coarse, low-variance
  signal being easier to fit than noisy lags on a mostly-zero panel; or overfitting to the training years'
  specific seasonal shape.

## Limitations and next steps

- **`month` dominance:** a feature-ablation run (drop `month` and see whether accuracy holds) is needed before
  treating the one window win as generalizing.
- **Per-cutoff refit:** refit the model at each of the four cutoffs, as the weekly-fit experiments do, and compare.
- **`n_estimators` floor:** extend the search below 100 (for example 20–150) to check whether the optimum is
  smaller.
- **Sensitivity sweep:** the single 30-evaluation TPE search covers a wide joint space, but a targeted
  one-parameter sweep (for example depth only) would make the hyperparameter story directly comparable with Random
  Forest's.
- **Segment metrics:** peak-season metrics are logged but are only informally comparable with the baseline's
  peak-season row (RMSE and bias, no WAPE per window). Peak here means windows whose origin month is a peak month.
