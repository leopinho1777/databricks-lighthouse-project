# XGBoost (task 3.3) — running notes

Working log, not a polished report. Status: hyperparameter search (30 Hyperopt evals) and the
official 4-window walk-forward both executed against the live workspace and logged under
`/Shared/02_model_comparison`. Bottom line: **beats `seasonal_naive` on 1/4 windows** (2024-12-31)
-- the first result any Stage 3 model has produced that beats the champion on any window at all
(`eros_randomforest` was 0/20 across all 5 configs tested).

## Design decisions

- **Grain**: daily, not weekly (unlike `eros_randomforest`). The protocol allows fitting at
  whatever grain suits the model ("free to fit at whatever grain suits it -- weekly, daily").
  Daily keeps the lag/rolling features (`trailing_qty_7d/28d/91d`, `same_period_last_year_qty`,
  `rolling_std_28d`, `nonzero_days_trailing_91d`) at native resolution.
- **Single-shot 91-day total**, not 91 daily predictions, not a weekly-then-summed prediction
  like RF -- sidesteps recursive-forecast error compounding entirely, same aggregate the
  baseline is scored on.
- **Frozen feature set compliance**: `month` (categorical, not dummy-encoded -- XGBoost handles
  categoricals natively via `enable_categorical=True`, dummies aren't needed for a tree model)
  + explicit `trend` (days since `DENSE_START` = 2020-01-01), per `10_frozen_feature_set.md`'s
  mandatory structural control for any tree-based Stage 3 model. Holiday/weather/economic/
  marketing NOT re-added -- already tested and rejected centrally.
- **`demand_category` as a direct model input**, not just a post-hoc diagnostic like RF's
  approach -- a deliberately different design choice, letting the model condition on it directly
  rather than testing whether tree splits can implicitly recover the segmentation.
- **Hyperparameters via Hyperopt** (30 evals, TPE), tuned on a validation fold (`TUNE_CUTOFF` =
  2024-06-30) strictly earlier than the 4 official cutoffs, so official numbers never leak into
  model selection.
- Data snapshot: `data_delta_version=5`. Library versions: xgboost=`3.4.1`, hyperopt=`0.3.0`,
  pandas=`2.3.3`, numpy=`1.26.4`, mlflow=`3.16.0`.

## Results

### Official walk-forward vs. `seasonal_naive_genuine_91d_v2`

| cutoff | actual_total | WAPE (xgboost) | WAPE (baseline) | delta | beats_baseline |
|---|---|---|---|---|---|
| 2024-12-31 | 46,163 | 77.09% | 78.84% | **-1.75pp** | **True** |
| 2025-04-01 | 23,216 | 104.83% | 84.43% | +20.40pp | False |
| 2025-07-01 | 17,354 | 124.60% | 88.05% | +36.55pp | False |
| 2025-09-30 | 41,435 | 81.47% | 79.89% | +1.57pp | False |

**1/4 windows beat baseline** -- the only positive result any Stage 3 model has produced so far
(`eros_randomforest`: 0/20 across its full sweep). Still loses badly on 2025-04-01 and
2025-07-01 specifically -- worth comparing against RF's per-window pattern, since RF's worst
window was also 2025-04-01 (and 2025-07-01 carries RF's documented ~9.5% actual-demand-drift
caveat from the weekly-grain straddle; this run reads `fct_sales` directly at daily grain, so
that specific caveat does not apply here, but the two models agreeing on which window is
hardest is worth a closer look before assuming it's model-specific).

### Per-segment (post-hoc diagnostic; `demand_category` is also a direct model input here)

| category | rmse | bias |
|---|---|---|
| intermittent | 5.72 | 1.27 |
| lumpy | 4.77 | 0.46 |

Both positive bias (under-forecasting -- the expensive failure mode, stockouts). Notably lower
than RF's best config (`depth10`: intermittent rmse=6.44/bias=3.48, lumpy rmse=5.05/bias=2.46) on
both RMSE and bias, though the two aren't perfectly comparable (different grain, RF's bias
figures are at weekly-summed-to-91d, not the same feature set).

### Feature importance -- open item, not fully explained

```
month                       64.7%
trend                       10.0%
product_variant_id           9.7%
demand_category               3.5%
day_of_week                   2.7%
location_id                   2.1%
trailing_qty_91d              1.3%
nonzero_days_trailing_91d     1.3%
same_period_last_year_qty     1.3%
rolling_std_28d               1.2%
trailing_qty_28d              1.1%
trailing_qty_7d               1.1%
```

**Flagging this rather than glossing over it**: `month` alone accounts for nearly two-thirds of
total importance, while all six recent-sales-history features combined (the trailing sums,
same-period-last-year, rolling std, nonzero-days) sum to under 7% -- the features that would
intuitively carry the strongest signal for predicting future sales are nearly ignored relative
to "which calendar month does the window start in." Plausible explanations, not yet
distinguished: (a) genuine seasonality dominance, consistent with this catalog's documented
strong peak-season effect; (b) the model finding it easier to fit the 91-day-ahead target via a
coarse, low-variance calendar signal than via noisier lag features on a catalog that's
92.9%-zero at points; (c) some degree of overfitting to the training period's specific seasonal
shape rather than a portable seasonal effect. Not resolved this session -- a natural follow-up
before trusting this model's out-of-sample generalization is a feature-ablation run (drop
`month`, see whether accuracy holds or collapses) and/or checking whether importance
concentration on `month` differs across the hyperopt trials, not just the final refit.

## Hyperparameters selected

```
max_depth=10, learning_rate=0.0235, n_estimators=100, subsample=0.999,
colsample_bytree=0.853, min_child_weight=4, reg_alpha=7.48, reg_lambda=2.92
```

`n_estimators=100` landed at the **floor** of the searched range (100-800) -- worth extending the
search lower in a follow-up (e.g. 20-150) rather than assuming 100 is a true interior optimum.
`reg_alpha=7.48` is near the top of its searched range (0.0001-10), consistent with a fairly
heavily regularized model -- plausibly related to the low reliance on the noisier lag features
noted above.

## Open items for the team

- **`month` dominance (64.7% importance)** -- the standalone open item from this session, see
  above. Needs a feature-ablation follow-up before treating this model's 1/4 result as fully
  trustworthy generalization vs. a narrower seasonal-fit artifact.
- **2025-04-01 and 2025-07-01 are the worst windows here, same as for RF** -- worth checking
  whether this is a property of those specific windows (e.g. an unusual demand shift not
  captured by any model class tried so far) rather than a per-model weakness, once more Stage 3
  models are in.
- **`n_estimators` search floor** -- rerun the Hyperopt search with a lower floor (e.g. 20) to
  check whether the true optimum is even smaller than 100.
- No systematic hyperparameter-sensitivity sweep beyond the single Hyperopt search was done this
  session (unlike RF's one-parameter-at-a-time runs) -- the 30-eval TPE search already covers a
  wide joint space, but a targeted follow-up (e.g. depth-only sweep, matching RF's format) would
  make the two models' hyperparameter stories more directly comparable.
