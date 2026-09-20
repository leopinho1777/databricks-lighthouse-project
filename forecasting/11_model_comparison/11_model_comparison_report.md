# Stage 3 — Final model comparison (task 3.7, input to 3.8)

**Script:** [`build_comparison.py`](build_comparison.py) · **Output:** [`output/`](output/) · **MLflow:** `/Shared/02_model_comparison`, run `final_comparison_3_7`

Nothing was refit for this report. Every number comes from the `*_window_totals.csv` files the
experiments already committed, re-scored through the shared protocol in
[`experiments/_shared/evaluate.py`](../experiments/_shared/evaluate.py) and compared against the committed
`seasonal_naive_genuine_91d_v2` baseline, exactly as `compare_to_baseline()` does. Nothing under
`09_baseline_close_out/` was touched or recomputed.

## TL;DR

- **No trained model beats the champion (seasonal naive) convincingly.** None wins even 3 of the 4 windows.
  XGBoost and the panel regression with smearing each win **one** window (2024-12-31, by 1.8pp and 0.8pp),
  which is inside the noise of a 4-window test. Mean WAPE: champion **82.8%**, everything else **95.9-100.1%**.
- **Best of what was tested:** on the official metric (portfolio WAPE per window) that is the seasonal-naive
  champion. Among the trained models it is **XGBoost v1**: lowest per-series RMSE and bias, the only model
  tied with the champion on the two peak windows (79.2% vs 79.3%), and the lowest category-level WAPE.
  The panel regression with Duan smearing is a close second.
- **"Best of what was tested" does not mean "good".** At SKU x location, every model sits at 77-132% WAPE in
  every window: the error is about as large as the demand being predicted. The forecasts only become usable
  one level up (category x location: XGBoost 15-31%, smearing 11-39%).
- **The data explains this**, not a lack of effort on the models: 25-59% of series sell nothing in a given
  91-day window, even a perfect model would carry ~27-45% WAPE from count noise alone, the annual seasonal
  cycle is already what the champion encodes, and Stage 2 found no external signal (holidays, weather,
  economy, marketing) for a richer model to exploit. Details below.
- **Scoring-convention caveat:** the committed baseline WAPE is computed only over series that sold something,
  while the models are scored on all 6,054 series. See [Caveats](#caveats); this report does not claim the
  ranking is immune to that choice.

## What was compared and how

Fifteen committed configurations from five model families, all scored on the same protocol: total demand
over a 91-day window per (`product_variant_id`, `location_id`), four non-overlapping rolling origins
(2024-12-31, 2025-04-01, 2025-07-01, 2025-09-30), training only on data up to each cutoff, WAPE per window
reported per window rather than only averaged. MAPE/sMAPE are excluded (`05_croston_sba` showed they are
structurally uninformative on this catalog), although the task tracker's wording still lists MAPE.

| Family | Owner | Target | Windows | Tuning |
|---|---|---|---|---|
| Random Forest (5 configs) | `eros_randomforest` | log1p | weekly fit, straddle week dropped | one-parameter-at-a-time sweep |
| Prophet (5 configs) | `eros_prophet` | log1p | weekly fit, straddle week dropped | one-parameter-at-a-time sweep |
| SARIMA (2 configs) | `pinho_sarima` | log1p | weekly fit, straddle week dropped | fixed order, no per-series search |
| XGBoost (1 config) | `gabriel_xgboost` | raw counts | exact 91 days | Hyperopt, 30 evals on an earlier fold |
| FE panel regression (2 configs) | `eva_regression` | log1p | exact 91 days (weekly fit prorated by day) | none (Stage 2 specification) |

Task 3.1 is covered by the FE panel regression (log-linear with entity fixed effects), not by a scikit-learn
`LinearRegression`. The main table shows the champion, the lowest-mean-WAPE configuration of each family, and
both panel-regression variants (the uncorrected run is the reference for the smearing correction). Every
configuration is in the [appendix](#appendix-every-committed-configuration). Picking the best configuration per
family on the same four windows it is scored on is mildly optimistic for the families that swept several
configs; it does not change any ranking here because the gaps to the champion are far larger than the gaps
between configs of one family.

**Peak-season slice.** The tracker asks for a peak-season-only slice. The per-model `*_peak_window_totals.csv`
files are not comparable (peak *weeks* for RF/Prophet/SARIMA, an origin-month flag for XGBoost, nothing for the
panel regression), so this report defines it at window level using the peak months already used everywhere in
Stage 3 (1-4 and 10-12): windows 1 (Jan-Mar) and 4 (Oct-Dec) are **peak**, windows 2 (Apr-Jun, 32% of days in
peak months) and 3 (Jul-Sep, 0%) are **off-peak**. Pooled WAPE over each pair is
`sum(abs error) / sum(actual)`, which also works for the champion's committed portfolio numbers.

## Results

### SKU x location portfolio WAPE (%)

| Model | 2024-12-31 (peak) | 2025-04-01 | 2025-07-01 | 2025-09-30 (peak) | Mean | Peak | Off-peak | Wins vs champion |
|---|---|---|---|---|---|---|---|---|
| seasonal_naive (champion) | 78.8 | 84.4 | 88.1 | 79.9 | 82.8 | 79.3 | 86.0 | - |
| Panel regression (uncorrected) | 87.1 | 100.5 | 107.0 | 89.0 | 95.9 | 88.0 | 103.3 | 0/4 |
| Prophet changepoint rigid | 87.4 | 102.2 | 104.7 | 89.5 | 96.0 | 88.4 | 103.4 | 0/4 |
| XGBoost v1 | 77.1 | 104.8 | 124.6 | 81.5 | 97.0 | 79.2 | 113.3 | 1/4 |
| RF depth10 | 88.0 | 107.0 | 104.0 | 89.7 | 97.2 | 88.8 | 105.6 | 0/4 |
| SARIMA d=0 + trend | 93.4 | 105.1 | 109.3 | 92.6 | 100.1 | 93.0 | 107.0 | 0/4 |
| Panel regression + Duan smearing | 78.1 | 109.5 | 131.7 | 81.3 | 100.1 | 79.6 | 119.0 | 1/4 |

Two patterns matter more than the ranking:

1. **The champion wins by winning the quiet windows.** On the two peak windows XGBoost (79.2%) and smearing
   (79.6%) are level with it (79.3%); on the two off-peak windows they are 27-33pp worse (113.3% and 119.0%
   against 86.0%). The other four models are 8-14pp behind on peak and 17-21pp behind off-peak.
2. **Two different failure modes.** The log-target models (RF, Prophet, SARIMA, uncorrected panel regression)
   are dominated by systematic *under*-forecasting; XGBoost and smearing have removed most of that bias and
   instead lose to dispersion in the trough windows, where they spread forecast onto series that then sell
   nothing (next section).

### Bias and per-series error

Bias is `actual - forecast`, so positive means under-forecast (the stock-out direction).

| Model | Mean portfolio bias (% of actual) | Per-series RMSE mean | Per-series RMSE median | Per-series bias mean |
|---|---|---|---|---|
| seasonal_naive (champion) | 49.4\* | n/a | n/a | n/a |
| Panel regression (uncorrected) | 66.8 | 6.38 | 5.79 | 3.63 |
| Prophet changepoint rigid | 68.4 | 6.43 | 5.87 | 3.67 |
| XGBoost v1 | 20.2 | 5.69 | 4.92 | 1.24 |
| RF depth10 | 61.3 | 6.39 | 5.84 | 3.45 |
| SARIMA d=0 + trend | 67.0 | 6.80 | 6.29 | 3.67 |
| Panel regression + Duan smearing | 12.6 | 5.74 | 4.79 | 1.16 |

\*The champion's per-series RMSE/bias are not comparable (its committed metrics average n=1 groups over series
with actual > 0 only) and its portfolio bias excludes forecast placed on zero-sales series, so the 49.4% is not
like-for-like with the other rows.

XGBoost and smearing are clearly ahead on the metrics that do not depend on the scoring convention: per-series
RMSE (5.7 vs 6.4-6.8), per-series bias (1.2 vs 3.5-3.7) and portfolio under-forecast (13-20% vs 61-68%).

### Category x location portfolio WAPE (%)

Same predictions, summed to category x location. The champion has no committed category-level predictions,
so it is not in this table.

| Model | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Mean |
|---|---|---|---|---|---|
| Panel regression (uncorrected) | 71.4 | 64.0 | 60.9 | 70.9 | 66.8 |
| Prophet changepoint rigid | 70.5 | 65.1 | 66.1 | 72.0 | 68.4 |
| XGBoost v1 | 24.2 | 27.6 | 15.5 | 31.2 | 24.6 |
| RF depth10 | 73.1 | 29.1 | 69.3 | 73.9 | 61.4 |
| SARIMA d=0 + trend | 78.8 | 63.2 | 58.1 | 67.9 | 67.0 |
| Panel regression + Duan smearing | 39.1 | 11.4 | 26.2 | 33.9 | 27.7 |

For the log-target models the category-level WAPE is almost exactly their bias (uncorrected panel regression
2024-12-31: 71.4% WAPE and 71.4% bias; SARIMA 78.8% and 78.8%; Prophet 70.5% and 70.5%). Once noise averages
out, **their remaining error is entirely the systematic under-forecast**, not randomness.

## Who did best, and how good is that?

- **On the official metric, the seasonal-naive champion.** Lowest WAPE in 3 of 4 windows and the lowest mean
  (82.8%). Nothing tested displaces it on portfolio WAPE.
- **Best trained model: XGBoost v1.** It is the only model that matches the champion on peak windows, has the
  lowest per-series RMSE/bias and the lowest category-level WAPE (24.6% mean), and it did this with a
  tuned-on-an-earlier-fold pipeline, so its numbers are not selected on the test windows. The panel regression
  with smearing is within noise of it on RMSE, bias and peak windows, and has the single best category window
  (11.4%), but is the worst model in the off-peak windows.
- **These are the best results among the options tested, not good results.** A SKU x location WAPE of 77-132%
  means the absolute error is about as large as the demand itself. The recorded wins over the champion are 1.8pp
  and 0.8pp on one window each. None of this is enough to call a model "accurate" at SKU level; it is enough to
  say which of the tested approaches is least bad.
- **Category x location is where the forecasts are usable**, at 15-31% (XGBoost) or 11-39% (smearing) WAPE, in
  line with `08_decision_horizon_and_product_axis`'s finding that SKU-level error is not actionable while
  category-level error is.

## Why the data behaves this way

Each point below is evidence from this repo, tied to a result above.

1. **The demand is extremely intermittent.** `04_demand_classification` found 96.8% Intermittent, 3.2% Lumpy,
   0% Smooth and 0% Erratic. In a 91-day window a series sells 2.9-7.6 units on average, and **25-59% of series
   sell nothing at all** (table below). Small counts dominate the metric, so WAPE at SKU level stays high
   whatever the model.
2. **Even a perfect model would score badly at SKU level.** If every series' true rate were known and demand
   were Poisson, the best achievable WAPE would still be **27-45%** per window (table below). Real demand is
   more dispersed than Poisson (observed zero-share is 5x the Poisson expectation), so the true floor is higher.
   The 77-132% we see is therefore a mix of model error and irreducible noise, and we cannot separate the two
   with this data. This floor is an illustration under stated assumptions, not a measured limit.
3. **A zero-heavy target punishes the wrong prediction type.** The log1p models predict `expm1` of a mean log,
   which is the *median*; for a series that usually sells zero the median is zero, so these models
   under-forecast total demand by 61-68% in the main table (bias table; 43-68% across every log-target config in the appendix) and their
   category-level error equals that bias. XGBoost
   (raw counts) and Duan smearing target the mean, cut bias to 13-20%, and that, more than model class, is what
   separates the top two from the rest. The price is forecast placed on series that then sell nothing
   (~8-12k units per window against 3-4k for the log models), which is why they lose in the trough windows.
4. **Strong annual seasonality favours the champion.** Window volume swings 2.7x (46.2k units in 2024-12-31,
   17.4k in 2025-07-01). "Same period last year" encodes that cycle for free. The trained models only see
   month dummies (the one feature Stage 2 kept), and XGBoost puts 64.7% of its importance on `month`.
   Their extra machinery has little to add on top of the seasonal shape, and they lose most off-peak.
5. **Smooth ~14-17%/year growth.** The champion has no trend and under-forecasts every window (bias positive
   in all four). Trees cannot extrapolate a trend (RF), a rigid Prophet trend beat a flexible one, and SARIMA
   with `d=0` plus a trend term beat `d=1`, which over-differenced. Growth is real and worth modelling, but it
   moves accuracy by single-digit points, not by the gap between 80% and 25%.
6. **No external signal to exploit.** Stage 2 found holidays, weather, economic indicators and marketing add
   ~0 to accuracy; only calendar survives. Prophet without holidays is within 0.22pp of default Prophet. The
   source is a mock database (see the project notes), i.e. a simple seasonal-plus-trend-plus-noise process:
   a richer model has little more to learn than the seasonal-naive rule already captures.
7. **Aggregation is where the signal is.** Summing SKUs to categories turns 25-59% zero-sales series into
   smooth totals (`08`: 92.4% Smooth at category x location monthly) and drops error from ~80-130% to 11-39%
   for the two mean-targeting models.
8. **Four windows of one year cannot separate small differences.** A 1-2pp gap (every "win" over the champion
   here) is not distinguishable from window-to-window variation.

### Data behaviour per window

| Window (cutoff) | Peak? | Actual units | Units / series | Series with zero sales (%) | Poisson-expected zeros (%) | Poisson noise-floor WAPE (%) |
|---|---|---|---|---|---|---|
| 2024-12-31 | yes | 46,163 | 7.63 | 24.9 | 4.9 | 27.4 |
| 2025-04-01 | no | 23,216 | 3.83 | 49.5 | 10.6 | 38.7 |
| 2025-07-01 | no | 17,354 | 2.87 | 58.8 | 15.1 | 44.7 |
| 2025-09-30 | yes | 41,435 | 6.84 | 29.0 | 5.4 | 29.0 |

Rate per series = its 4-window mean scaled by each window's share of total volume, so the seasonal swing is
kept. Actuals are from the exact-window runs (XGBoost) so they match the baseline's window definition.

### Forecast units placed on series that sold nothing in the window

| Model | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 |
|---|---|---|---|---|
| Panel regression (uncorrected) | 3,287 | 4,133 | 3,960 | 3,485 |
| Prophet changepoint rigid | 3,389 | 3,956 | 3,562 | 3,345 |
| XGBoost v1 | 8,684 | 8,391 | 10,335 | 8,264 |
| RF depth10 | 3,077 | 7,989 | 3,220 | 3,108 |
| SARIMA d=0 + trend | 2,446 | 4,133 | 4,443 | 3,845 |
| Panel regression + Duan smearing | 7,003 | 11,460 | 12,526 | 7,929 |

## Caveats

- **Scoring convention (not resolved in this report).** The committed baseline's WAPE is computed only over
  series that sold something in the window: `actuals_for_window()` in `09_baseline_close_out/run_genuine_baseline.py`
  returns only those, and the score merges from it. `evaluate()` scores all 6,054 series, so every model is
  also charged for forecast it places on series that sold nothing (table above). The team's own separate
  re-analysis with the convention aligned, which is not part of this repo and was not re-run for this report,
  reached the same conclusion: no model beats the baseline in at least 3 windows, so the conclusion is
  reported here as that team finding. For transparency, the one direction the committed files let us check:
  scoring the trained models the baseline's way (actual > 0 only) lowers their WAPE, to 58-69% for XGBoost and
  60-63% for smearing, and 70-88% for the rest (table below), which would put XGBoost and smearing below the
  champion's 79-88% in every window. So the ranking does depend on which way the two scores are aligned, and this
  report does not claim it is convention-proof. What holds either way is the level: no model is accurate at
  SKU x location.
- **Windows are not identical across families.** XGBoost and the panel regression use the exact 91-day windows.
  RF, Prophet and SARIMA fit weekly and drop the week straddling the cutoff, so their scored window is shifted by
  up to ~5 days and their `actual_total` drifts from the baseline's by up to 9.49% (2025-07-01). Treat those
  three families' 2025-07-01 numbers with reduced confidence. Production actuals have also drifted 0.55-1.67%
  upward since the baseline was computed (`experiments/eva_regression/README.md`). `compare_to_baseline()` warns about this on
  every run and it was left as is.
- **Targets and tuning differ.** Four families fit `log1p`; XGBoost fits raw counts. XGBoost had a 30-eval
  Hyperopt search, the log models had one-parameter sweeps or none. Part of XGBoost's advantage is the target
  choice, not the algorithm.
- **XGBoost is not refit per window.** It fits one model on history whose 91-day target ends by 2024-12-31 and
  applies it at all four cutoffs (features are rebuilt from data up to each cutoff, so nothing leaks). The other
  families refit at every cutoff, so XGBoost's later windows are scored by a model that has not seen any 2025
  data. A per-cutoff refit is untested and could move its off-peak windows in either direction.
- **Baseline per-series metrics do not exist in comparable form**, so RMSE/bias columns show `n/a` for the
  champion.

### Sensitivity: WAPE (%) if models are scored on series with actual > 0 only (the baseline's convention)

| Model | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Champion (committed) |
|---|---|---|---|---|---|
| Panel regression (uncorrected) | 80.0 | 82.7 | 84.2 | 80.6 | |
| Prophet changepoint rigid | 80.0 | 84.2 | 85.7 | 81.5 | |
| XGBoost v1 | 58.3 | 68.7 | 65.0 | 61.5 | |
| RF depth10 | 81.2 | 70.6 | 86.7 | 82.3 | |
| SARIMA d=0 + trend | 88.0 | 86.3 | 85.5 | 83.5 | |
| Panel regression + Duan smearing | 62.9 | 60.1 | 59.5 | 62.1 | |
| seasonal_naive (champion) | 78.8 | 84.4 | 88.1 | 79.9 | as committed |

## What is not covered

- **Phase 1 intermittent-demand methods (Croston, SBA, ADIDA) are not in this comparison.** They are the
  textbook answer to the demand pattern in point 1, but were evaluated in `05`/`06` on a different daily 2025
  holdout, not under the 91-day protocol, so they are not scored here.
- **Moving average** (the second Phase 1 baseline) is left out of the main table; the champion beat it in every
  window (`09_baseline_close_out`).
- **Per-series champion metrics** (RMSE/bias per series, category level) cannot be produced without recomputing
  the baseline, which was ruled out for this report.

## Input to 3.8 (the champion decision is the team's)

- Nothing tested justifies replacing `seasonal_naive_genuine_91d_v2` as the SKU x location reference.
- **XGBoost v1** is the leading challenger. The tracker's promotion rule (task 4.6) requires beating the champion
  on peak-season performance; XGBoost currently *ties* it (79.2% vs 79.3%), which does not clear that rule.
- The most defensible product for the client is the **category x location** forecast, with SKU x location shown
  as the honest accuracy statement.

## Suggested next steps

1. A trend-adjusted seasonal naive (last year's window times the observed growth factor): cheap, and directly
   addresses the champion's positive bias in every window.
2. Put RF, Prophet and SARIMA on a mean-targeting basis (smearing, or a Poisson/Tweedie objective) before
   comparing them again, since their current ranking mostly reflects the median-versus-mean gap.
3. Season-specific smearing for the panel regression (a single global factor over-corrects the trough).
4. XGBoost `month`-ablation and a lower `n_estimators` floor, both already listed in its notes.
5. Align the scoring convention (all series for everyone) and re-run the champion on the current snapshot in one
   pass, so future comparisons do not depend on the caveat above.

## Appendix: every committed configuration

SKU x location WAPE (%); `Windows` is the window definition (`exact` or `weekly-straddle`, see Caveats).

| Model | Target | Windows | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Mean | Wins | Bias % | RMSE mean |
|---|---|---|---|---|---|---|---|---|---|---|
| Panel regression (uncorrected) | log1p | exact | 87.1 | 100.5 | 107.0 | 89.0 | 95.9 | 0/4 | 66.8 | 6.38 |
| Panel regression + Duan smearing | log1p | exact | 78.1 | 109.5 | 131.7 | 81.3 | 100.1 | 1/4 | 12.6 | 5.74 |
| Prophet changepoint rigid | log1p | weekly-straddle | 87.4 | 102.2 | 104.7 | 89.5 | 96.0 | 0/4 | 68.4 | 6.43 |
| Prophet no holidays | log1p | weekly-straddle | 87.0 | 102.6 | 106.1 | 88.6 | 96.1 | 0/4 | 64.5 | 6.37 |
| Prophet default | log1p | weekly-straddle | 87.0 | 102.8 | 106.3 | 88.8 | 96.2 | 0/4 | 64.0 | 6.37 |
| Prophet changepoint flexible | log1p | weekly-straddle | 87.2 | 105.6 | 108.2 | 88.8 | 97.4 | 0/4 | 58.6 | 6.40 |
| Prophet multiplicative seasonality | log1p | weekly-straddle | 93.1 | 105.6 | 111.1 | 91.7 | 100.4 | 0/4 | 53.6 | 6.66 |
| RF depth10 | log1p | weekly-straddle | 88.0 | 107.0 | 104.0 | 89.7 | 97.2 | 0/4 | 61.3 | 6.39 |
| RF leaf20 | log1p | weekly-straddle | 87.0 | 108.6 | 104.3 | 91.1 | 97.7 | 0/4 | 60.2 | 6.43 |
| RF sqrtfeatures | log1p | weekly-straddle | 91.0 | 116.2 | 108.6 | 92.2 | 102.0 | 0/4 | 56.5 | 6.74 |
| RF depth20 | log1p | weekly-straddle | 87.3 | 125.4 | 105.9 | 91.5 | 102.5 | 0/4 | 55.7 | 6.68 |
| RF unbounded | log1p | weekly-straddle | 99.4 | 165.2 | 110.5 | 97.7 | 118.2 | 0/4 | 42.7 | 7.81 |
| SARIMA d=0 + trend | log1p | weekly-straddle | 93.4 | 105.1 | 109.3 | 92.6 | 100.1 | 0/4 | 67.0 | 6.80 |
| SARIMA d=1 | log1p | weekly-straddle | 94.0 | 110.6 | 115.0 | 96.8 | 104.1 | 0/4 | 58.9 | 7.01 |
| XGBoost v1 | raw counts | exact | 77.1 | 104.8 | 124.6 | 81.5 | 97.0 | 1/4 | 20.2 | 5.69 |

## Reproduce

```bash
uv run python forecasting/11_model_comparison/build_comparison.py
```

Reads the committed `*_window_totals.csv` files plus one read-only `dim_products` query (category map) through
`experiments/_shared/evaluate.py`; asserts that each configuration's recomputed WAPE matches the number its own
run reported (within 0.01pp) and that it covers 6,054 series x 4 windows. Regenerates every table above into
`output/report_tables.md`.
