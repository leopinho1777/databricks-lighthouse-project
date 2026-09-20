# Random Forest (task 3.2)

One pooled `RandomForestRegressor` fit across the whole catalog (~6,054 product × location series),
scored under the shared Stage 3 protocol (`../_shared/evaluate.py`) and logged to the
`/Shared/02_model_comparison` MLflow experiment. Five configurations are run.

**Result:** no configuration beats the `seasonal_naive_genuine_91d_v2` champion in any window (0 of 20
window comparisons). The best configuration is `random_forest_depth10`. Depth is the dominant
hyperparameter: capping it forces the forest to share information across the ~6,054 entities instead of
memorizing each entity through raw ID codes.

## Hypothesis

A single flexible model with no explicit Smooth/Intermittent/Lumpy label can approximate the
segment-aware treatment that `04_demand_classification` (96.8% Intermittent / 3.2% Lumpy, no
Smooth/Erratic series at this grain) and `05_croston_sba` imply. The forest can learn that split
implicitly through `entity_mean_log_qty × month_*` splits. The segment label is deliberately not an
input; each run reports per-segment RMSE/bias afterwards (`<run>_segment_summary.csv`, joined from
`04_demand_classification/output/demand_classification.csv`), so the "one flexible model" and "segmented
method" strategies can be compared rather than assumed equivalent.

## Design

- **Grain and target.** Weekly panel from `load_weekly_panel()` (`10_feature_engineering/_shared/panel_regression.py`),
  target `log1p(qty_sold_net)`, back-transformed with `expm1().clip(min=0)`, the same convention as the
  Stage 2 panel regression. One `predict()` call per cutoff covers all 13 horizon weeks, because the
  features are known for any future week (no recursive forecasting).
- **Inputs** (`RF_FEATURES`): the frozen calendar feature (`month_2`…`month_12`) and `trend`
  (`10_feature_engineering/10_frozen_feature_set.md`), plus entity identity: `entity_mean_log_qty` (a
  mean-log-quantity encoding, the practical analogue of an absorbed entity fixed effect) and integer codes
  `product_variant_id_code` / `location_id_code` for entity × season interactions a fixed-effect intercept
  cannot represent. Codes are fit on each cutoff's training categories and reused for scoring; an entity
  absent from the training window gets `-1`.
- **Window alignment.** The protocol's four cutoffs (2024-12-31, 2025-04-01, 2025-07-01, 2025-09-30) are all
  Tuesdays and weeks are Monday-anchored, so the week containing a cutoff straddles it. That week is
  excluded from both sides: training keeps weeks whose Monday is ≤ cutoff − 6 days (the whole week is ≤
  cutoff) and the scored horizon starts at the first Monday after the cutoff (the whole week is > cutoff).
  Summing a straddling week would either pull future days into training or count already-known days as
  out-of-sample. The cost is a window shifted by up to a few days relative to the baseline's exact
  cutoff+1 … cutoff+91 (see "Actual demand versus the baseline" below).
- **Peak months** are computed once from data ≤ 2024-12-31 (matching the baseline's reference period) and
  reused for all four cutoffs.
- **Trend limitation.** Trees cannot extrapolate `trend` beyond its training range, so the forest's response
  to continued growth flattens for later cutoffs.
- **Cold start.** A series with no history in the training window forecasts 0, the same convention the
  baseline's `COALESCE(0)` uses.
- **Tuning.** No automated search (that is XGBoost's task): the default configuration, then one
  hyperparameter category at a time.

## Running it

```bash
uv sync --dev --group forecasting
uv run python forecasting/experiments/eros_randomforest/train_random_forest.py               # all five configs
uv run python forecasting/experiments/eros_randomforest/train_random_forest.py random_forest_depth10
```

Requires the dev profile in `~/.dbt/profiles.yml` and the scratch table
`<catalog>.<dev_schema>_forecasting_scratch.fact_demand_daily` (`../../02_schema_design/build_prototype.py`).
Each run logs parameters, per-window WAPE / actual total / bias, per-series RMSE and bias (overall and
peak-season), `beats_baseline_pct`, the final-cutoff model (logged with
`serialization_format="cloudpickle"`, since the default `skops` format is not a project dependency), and the CSVs in
`output/`. Data snapshot: Delta version 4 (2026-09-11 19:44:50); scikit-learn 1.9.1, pandas 2.3.3,
numpy 1.26.4, mlflow 3.16.0.

| Output file | Content |
|---|---|
| `<run>_window_totals.csv` | Per series × cutoff `actual` and `pred` (input to `../../11_model_comparison`) |
| `<run>_peak_window_totals.csv` | The same, restricted to peak-season weeks |
| `<run>_compare_to_baseline.csv` | Per-window WAPE against the champion |
| `<run>_feature_importance.csv` | Mean-decrease importance per cutoff and averaged |
| `<run>_segment_summary.csv` | Per-segment RMSE and bias |

## Actual demand versus the baseline

`compare_to_baseline()` warns that this experiment's `actual_total` differs from the baseline's by up to
9.49%, identically in every run:

| Cutoff | This experiment | Baseline | Difference |
|---|---|---|---|
| 2024-12-31 | 45,341 | 45,909 | −1.24% |
| 2025-04-01 | 21,902 | 23,007 | −4.80% |
| 2025-07-01 | 18,688 | 17,069 | **+9.49%** |
| 2025-09-30 | 42,035 | 40,968 | +2.60% |

Two effects, isolated with direct SQL against `fct_sales` and `fact_demand_daily`:

- **Quantity definition** (`fact_demand_daily`'s net `qty_sold_net` against `fct_sales`' gross `quantity`, same
  dates): small and consistent, −0.65% to −0.67% on both windows tested.
- **Window shift** (same net quantity, the baseline's exact dates against the straddle-shifted dates): −0.59% on
  the 2024-12-31 window but **+8.41%** on 2025-07-01, the dominant driver of that window's drift. The horizon
  starts about 5 days later than the baseline's, so early October (included here, absent from the baseline)
  carries meaningfully higher demand than early July (in the baseline, absent here).

The drift is a structural consequence of weekly bucketing and does not indicate a quantity-definition
mismatch. Read the 2025-07-01 window's WAPE and `beats_baseline` with reduced confidence relative to the other
three.

## Results

Portfolio WAPE (%) at SKU × location, all 6,054 series (lower is better):

| Configuration | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Beats champion |
|---|---|---|---|---|---|
| `random_forest_baseline` (300 trees, no depth cap, `min_samples_leaf=1`, `max_features=1.0`) | 99.37 | 165.25 | 110.46 | 97.72 | 0/4 |
| **`random_forest_depth10`** (`max_depth=10`) | 87.95 | **107.04** | 103.96 | **89.72** | 0/4 |
| `random_forest_depth20` (`max_depth=20`) | 87.34 | 125.42 | 105.89 | 91.49 | 0/4 |
| `random_forest_leaf20` (`min_samples_leaf=20`) | 87.02 | 108.55 | 104.31 | 91.07 | 0/4 |
| `random_forest_sqrtfeatures` (`max_features="sqrt"`) | 91.04 | 116.19 | 108.62 | 92.16 | 0/4 |
| Champion (`seasonal_naive_genuine_91d_v2`) | 78.84 | 84.43 | 88.05 | 79.89 | n/a |

`depth10` has the lowest WAPE in three of the four windows and is effectively tied with `leaf20` in all four
(`depth20` is 0.6 pp lower on 2024-12-31 and `leaf20` 0.35 pp lower than `depth10` on 2025-07-01).

Per-series RMSE and bias by demand segment (bias = actual − forecast, positive means under-forecast):

| Configuration | Intermittent RMSE / bias | Lumpy RMSE / bias |
|---|---|---|
| `baseline` | 7.86 / 2.63 | 6.29 / 1.72 |
| `depth10` | 6.44 / 3.48 | 5.05 / 2.46 |
| `depth20` | 6.72 / 3.26 | 5.45 / 2.17 |
| `leaf20` | 6.47 / 3.43 | 5.08 / 2.39 |
| `sqrtfeatures` | 6.78 / 3.22 | 5.60 / 2.35 |

Mean feature importance (%), by group:

| Configuration | `trend` | `entity_mean_log_qty` | ID codes (product + location) | `month_*` combined |
|---|---|---|---|---|
| `baseline` | 37.4 | 26.4 | 31.5 (24.7 + 6.8) | 4.7 |
| `depth10` | 30.8 | 28.1 | 9.9 (7.8 + 2.1) | 31.2 |
| `depth20` | 35.8 | 28.2 | 30.6 (24.3 + 6.3) | 5.4 |
| `leaf20` | 18.0 | 35.6 | 39.1 (31.4 + 7.8) | 7.2 |
| `sqrtfeatures` | 23.4 | 36.7 | 38.9 (36.0 + 2.9) | 1.0 |

## Interpretation

- **Depth is the lever.** The unbounded forest overfits badly (165% WAPE on 2025-04-01). A depth of 10 allows at
  most 2^10 = 1,024 leaves, fewer than the ~6,054 entities, so the forest is structurally forced to share
  information through `trend`, `month_*` and `entity_mean_log_qty` rather than memorize per-entity levels via
  the raw ID codes. Depth 20 and the unbounded/`leaf20`/`sqrtfeatures` configurations all put 31–39% of
  importance on the raw ID codes and lose the month signal (1–7% against 31% for `depth10`).
- **`leaf20` reaches the same accuracy as `depth10` through a different mechanism.** With about 250 weeks of
  history per entity, a minimum leaf size of 20 still allows near-per-entity leaves, so the forest keeps
  leaning on the ID codes. That two configurations with opposite feature reliance land on similar WAPE
  suggests the codes carry some real per-entity signal beyond `entity_mean_log_qty`.
- **Trend extrapolation is not the main driver.** The window that hurts most is 2025-04-01, not the latest
  cutoff (2025-09-30 is consistently among the better windows), so overfitting explains more of the gap than
  the tree extrapolation limit.
- **Systematic under-forecast.** Every configuration has positive bias (under-forecast), and the log1p target
  makes the forecast a conditional median, which for a mostly-zero series is close to zero. The same effect
  drives the log-target models in `../../11_model_comparison`.
- **The segmentation hypothesis is only partly answered.** A single forest does not close the gap to the
  non-segmented seasonal-naive baseline. Per-segment RMSE is lower for Lumpy than Intermittent in every run,
  but RMSE is not scale-normalized and Lumpy series may simply have different volumes, so it should not be
  read as "the forest handles lumpy demand better". Comparing against the segmented Croston/SBA per-series RMSE
  (`05_croston_sba`) is the input needed to settle it.

## Limitations and next steps

- `random_forest_depth10_nocode`: drop the raw ID codes and keep `entity_mean_log_qty` alone. In the
  configurations that do not cap depth the codes hold more importance than `entity_mean_log_qty` and the month
  terms combined (`sqrtfeatures`: 38.9% against 37.7%); whether `depth10` improves without them is untested.
- A finer depth sweep (5, 8, 12, 15) is warranted, since depth moved accuracy far more than leaf size or feature
  subsampling.
- Peak-season metrics are logged every run (`peak_rmse_mean`, `peak_bias_mean`) but are only informally
  comparable with the baseline's peak-season row, which reports RMSE and bias but not WAPE per window.
- Entity-code cold start (entities absent from a cutoff's training window) is not stress-tested.
