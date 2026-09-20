# SARIMA (task 3.5)

One `SARIMAX` per (`product_variant_id`, `location_id`) series, as the statistical benchmark for Stage 3.
Scored under the shared protocol (`../_shared/evaluate.py`) and logged to the `/Shared/02_model_comparison`
MLflow experiment. Two configurations are run over the full 6,054-series catalog and four cutoffs (24,216 fits
each).

**Result:** neither configuration beats the `seasonal_naive_genuine_91d_v2` champion in any window (0 of 8).
`sarima_d0_trend` (`d=0` with a constant trend term) is better than `sarima_baseline` (`d=1`) on all four windows,
because the log1p series are already stationary around a trend and first differencing over-differences them.
`sarima_d0_trend` is the SARIMA candidate carried into the cross-model comparison.

## Design

- **Per-series, full catalog.** SARIMA is inherently per-series ("the product's own historical values and
  seasonal patterns"). The full catalog is required, not optional: `compare_to_baseline()` checks the modeled
  `actual_total` per window against the full-catalog baseline within 0.5%, so a subsample would trip that check by
  construction.
- **Grain and target.** Weekly panel (`load_weekly_panel()`), `log1p(qty_sold_net)`. Month dummies
  (`month_2`…`month_12`) are exogenous regressors, so one `get_forecast(steps=13)` call covers the 13-week
  horizon with no recursive forecasting. The straddle-week handling is the same as Random Forest's, so
  `actual_total` per window is 45,341 / 21,902 / 18,688 / 42,035 units, up to 9.49% away from the baseline's on
  2025-07-01 (`../eros_randomforest/README.md`, "Actual demand versus the baseline").
- **Seasonality: `D=1, s=52`.** The annual cycle (Dec–Mar peak, Jun–Aug trough) is established in
  `01_data_exploration` and `03_granularity_baselines`, so seasonal differencing is applied directly.
  `seasonal_order=(0,1,0,52)` has no seasonal AR/MA terms: state-space cost scales with `s=52` regardless of how
  small `P`/`Q` are, so dropping them keeps the seasonal differencing without paying for `P`/`Q` across 24,216 fits.
  A `sarima_seasonal_ar` variant (`(1,1,0,52)`) is defined but commented out in `RUNS`.
- **Month dummies alongside `D=1`.** They capture a different thing: the deterministic calendar shape, where `D=1`
  captures stochastic year-over-year seasonal drift a fixed dummy cannot adapt to.
- **`p, q = (1, 1)` for every series.** Order selection is statsmodels-only (no `pmdarima` in the project's
  dependencies) and is checked by AIC on the portfolio aggregate, not searched per series.
- **Trend handling.** Both configurations are run, and the comparison against the champion decides:

  | Configuration | `order` | `seasonal_order` | Trend |
  |---|---|---|---|
  | `sarima_baseline` | (1,1,1) | (0,1,0,52) | none; growth through `d=1` |
  | `sarima_d0_trend` | (1,0,1) | (0,1,0,52) | `trend="c"` on the differenced scale |

  With `D=1` alone the seasonally differenced series has a non-zero mean (this year's week minus last year's is the
  growth), and SARIMAX only estimates that mean when told to via `trend=`.
- **Fit robustness.** `enforce_stationarity=False, enforce_invertibility=False, simple_differencing=True`,
  `maxiter=50`, which bounds per-fit cost and avoids hard failures on the catalog's many near-flat, near-zero
  series (96.8% Intermittent, 92.9% zero at this grain).
- **Output guard.** Any non-finite forecast, or any predicted week above `max(1000, 100 × the series' own
  historical peak week)`, is treated as a fit failure and replaced by the zero-forecast fallback. It is needed
  because, without `d=1` differencing, `enforce_stationarity=False` lets the optimizer pick an explosive AR root
  for a few series, and a 13-step forecast from such a root compounds exponentially without raising an exception.
  In `sarima_d0_trend` the guard fires on 5 of 24,216 fits (0.02%); without it a single series' forecast reaches
  3.5e189 and the portfolio WAPE becomes meaningless. `sarima_baseline` never triggers it.
- **Fallback rule.** On any fit exception the forecast is 0 for the horizon (the "no history → forecast 0"
  convention of the other experiments). Every failure is recorded per (series, cutoff) in `fit_diagnostics.csv`
  (`fallback=True`, `fit_error=<message>`).
- **"Converged" is a proxy.** statsmodels exposes no optimizer-agnostic convergence flag, so `converged` means
  no `ConvergenceWarning` was raised during `.fit()`. `pct_non_converged` is tracked separately from the
  failure rate.
- **Parallelism.** `joblib`'s default process (`loky`) backend, which gives real multi-core parallelism
  (`n_jobs=-1`). Workers re-import the script, so every warehouse or CSV read is in `_setup()`, called only from
  `__main__` in the parent process, never at module scope. Threads give no speedup because `SARIMAX.fit()` holds
  the GIL for most of a fit at this problem size.
- **Artifacts.** The final-cutoff fitted model of three fixed exemplar series is logged
  (`mlflow.statsmodels.log_model()`): the highest-volume series overall and the highest-volume series in each
  segment. Full-catalog diagnostics are in `<run>_fit_diagnostics.csv`, not in MLflow model artifacts.

## Order diagnostics

`python train_sarima.py --diagnose` (recorded once; not repeated per production run):

- **Augmented Dickey-Fuller on the portfolio aggregate (log1p, levels):** `regression="c"` stat −4.765
  (p = 0.0001); `regression="ct"` (trend-aware) stat −7.597 (p ≈ 0). Both reject the unit root.
- **Per-series ADF (10 Intermittent + 10 Lumpy, stratified by volume):** 20 of 20 reject the unit root at levels
  (p from 0.0067 to <0.0001).
- **First difference:** ACF at lag 1 is −0.352, the over-differencing signature.
- **AIC over (p,q) ∈ {(0,1), (1,0), (1,1)} at `d=1`:** (1,1,0) −137.7, (1,1,1) −137.0, (0,1,1) −136.2, close
  enough that (1,1) is kept.

The aggregate and the sampled series are stationary around a smooth trend, which is what the project's growth
looks like (a trend-stationary process, not a random walk), so `d=1` is not required. Dropping differencing
without a trend term would lose the only mechanism that tracks growth, hence `sarima_d0_trend` uses
`trend="c"` (SARIMAX applies it on the differenced scale, so it does not double-count growth alongside `D=1`).

## Running it

```bash
uv sync --dev --group forecasting
uv run python forecasting/experiments/pinho_sarima/train_sarima.py --diagnose            # order diagnostics
uv run python forecasting/experiments/pinho_sarima/train_sarima.py --pilot 100           # timed pilot
uv run python forecasting/experiments/pinho_sarima/train_sarima.py                       # both configs
uv run python forecasting/experiments/pinho_sarima/train_sarima.py sarima_d0_trend       # one config
SAMPLE_ENTITIES=200 uv run python forecasting/experiments/pinho_sarima/train_sarima.py   # mechanics check
```

`SAMPLE_ENTITIES` restricts the run to a small deterministic subset for a fast pipeline check; its results are
not comparable with the baseline and the drift warning is expected to fire. Authentication uses the token in the
`~/.dbt/profiles.yml` dev profile, so no interactive `databricks auth login` is needed.

**Timed pilot.** 100 series took 12.1 s (0.121 s per fit), which extrapolates to about 49 minutes for one full
configuration on 8 cores; the pair of configurations takes about 51 minutes in total. Library versions and the
Delta snapshot are logged as MLflow tags each run.

| Run | MLflow |
|---|---|
| `sarima_baseline` | [5890e375…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/5890e375e2884933977dc31ecd470235) |
| `sarima_d0_trend` | [0e6cf3a7…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/0e6cf3a743f54677b9ddb0733cd1c150) |

## Results

Portfolio WAPE (%) at SKU × location, all 6,054 series (lower is better):

| Configuration | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Beats champion |
|---|---|---|---|---|---|
| `sarima_baseline` (d=1) | 93.99 | 110.57 | 115.00 | 96.76 | 0/4 |
| **`sarima_d0_trend`** (d=0, trend `c`) | **93.37** | **105.12** | **109.27** | **92.64** | 0/4 |
| Champion (`seasonal_naive_genuine_91d_v2`) | 78.84 | 84.43 | 88.05 | 79.89 | n/a |

`sarima_d0_trend` improves on `sarima_baseline` by 0.6–5.7 pp in every window, with the largest gains on the two
middle cutoffs.

| Configuration | Intermittent RMSE / bias | Lumpy RMSE / bias | Fit failures | Non-converged |
|---|---|---|---|---|
| `sarima_baseline` | 7.05 / 3.20 | 5.79 / 2.27 | 0.00% | 63.34% |
| `sarima_d0_trend` | 6.84 / 3.71 | 5.50 / 2.66 | 0.02% (5 fits) | 62.17% |

Per-series RMSE is close between the two (the gain shows mainly in portfolio WAPE, since `d=0` plus a trend
tracks the catalog's aggregate growth better without uniformly improving every series), and both have positive
bias (under-forecast).

## Interpretation

- SARIMA is included as a well-established benchmark, not as an expected top performer. It does not beat the
  champion in any window with either configuration.
- Over-differencing is the main modeling result: the diagnostics and the WAPE comparison agree that `d=1` is the
  wrong way to carry the growth on this catalog.
- More than 60% of fits raise a `ConvergenceWarning` at `maxiter=50`, which is plausible for a fixed, unsearched
  order on heavily intermittent data. This bounds how much to trust individual series forecasts.
- The log1p target makes forecasts conditional medians, which explains the systematic under-forecast shared with
  the other log-target experiments.

## Limitations and next steps

- The order is one fixed `(p,d,q)(P,D,Q,s)` for the whole catalog. A per-series order search (a `pmdarima`
  dependency or a per-series AIC grid) is the follow-up if SARIMA turns out competitive enough to tune.
- The output guard is a general requirement for SARIMAX with `enforce_stationarity=False` across many series: a
  successful `.fit()` is not evidence that the forecast is usable.
- Exemplar models are chosen by raw volume, not by fit quality, so an exemplar can itself be a fallback or a
  non-converged fit.
- `sarima_d0_trend` departs from `10_feature_engineering/10_frozen_feature_set.md`'s original "growth through
  differencing" guidance for this model class; §2 and §9 of that document record the tested alternative.
