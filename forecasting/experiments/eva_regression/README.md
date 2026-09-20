# Panel regression under the Stage 3 protocol (task 3.1)

The Stage 2 specification — `log1p(qty) ~ month_2..month_12 + trend` with entity
fixed effects per (product_variant_id, location_id), estimated with
`linearmodels.PanelOLS(entity_effects=True)` — refit once per 91-day window and
scored through `experiments/_shared/evaluate.py`. This is the Stage 3 linear model:
a log-linear fixed-effects regression rather than a scikit-learn `LinearRegression`.
Two runs, both in `/Shared/02_model_comparison`: `panel_regression_fe_trend_month`
(uncorrected) and `panel_regression_fe_trend_month_smearing` (with Duan's smearing
correction).

## Running it

```bash
uv sync --dev --group forecasting
uv run python forecasting/experiments/eva_regression/run_panel_regression.py               # uncorrected run
SMEARING=1 uv run python forecasting/experiments/eva_regression/run_panel_regression.py    # smearing run
SAMPLE_ENTITIES=200 uv run python forecasting/experiments/eva_regression/run_panel_regression.py   # mechanics check
```

The scripts read the scratch table `<catalog>.<dev_schema>_forecasting_scratch.fact_demand_daily`
(`../../02_schema_design/build_prototype.py`). Outputs are prefixed with the run name in `output/`:
`_window_totals.csv` (input to `../../11_model_comparison`), `_baseline_comparison.csv`,
`_portfolio_metrics.csv`, `_portfolio_metrics_category.csv` and `_per_series_metrics.csv`.
`SAMPLE_ENTITIES` restricts the run to a subset for a fast check; its results are not comparable with the baseline.

**Headline: the regression does not beat the seasonal naive baseline at SKU x
location.** It wins one window of four, and only after a bias correction that
makes two other windows worse. It is, however, clearly usable at category x
location — where its best window reaches 11.4% WAPE.

## The numbers

Portfolio WAPE per window, SKU x location:

| Window | No correction | Smearing | Baseline (`seasonal_naive_genuine_91d_v2`) |
|---|---|---|---|
| 2024-12-31 | 87.09% | **78.08%** | 78.84% |
| 2025-04-01 | 100.47% | 109.45% | 84.43% |
| 2025-07-01 | 106.98% | 131.69% | 88.05% |
| 2025-09-30 | 88.98% | 81.28% | 79.89% |

Same predictions, summed to category x location:

| Window | No correction | Smearing |
|---|---|---|
| 2024-12-31 | 71.45% | 39.14% |
| 2025-04-01 | 64.04% | 11.41% |
| 2025-07-01 | 60.88% | 26.22% |
| 2025-09-30 | 70.92% | 33.90% |

Per series, across the four windows:

| | RMSE mean | RMSE median | Bias mean |
|---|---|---|---|
| No correction | 6.378 | 5.789 | 3.626 |
| Smearing | 5.737 | 4.792 | 1.163 |

## 1. Retransformation bias: the uncorrected run under-forecasts by ~71%

Window 1 predicted 13,181 units against 46,163 actual. This is not the model
failing to see demand: it is fitting on `log1p(qty)` and predicting `expm1(x'b)`,
which estimates the conditional **median**, not the mean. On a catalog where
96.8% of series are Intermittent, the median of a series' weekly demand is
frequently 0 while its mean is not, so the gap is structural and predictable
from the specification alone.

Stage 2's weekly MAPE hides this, because a proportional under-prediction is
diluted across 92.9% zero rows. Summing into a 91-day window total — what this
protocol scores — makes it immediately visible. **This is an argument for the
window-total protocol itself**, not only a finding about this model.

## 2. Duan's smearing estimator corrects the aggregate but over-corrects the low season

The standard non-parametric correction: multiply `exp(x'b)` by the mean
exponentiated training residual, then subtract 1. It assumes the residual
distribution out of sample matches the training one, so it is reported next to the
uncorrected run rather than replacing it.

It does what it claims: mean bias per series drops from 3.63 to 1.16 units, RMSE
mean from 6.38 to 5.74, and window 1 goes from losing by 8.3pp to **beating the
baseline by 0.76pp**.

But portfolio WAPE gets *worse* in windows 2 and 3 — 100.5% to 109.5%, and 107.0%
to 131.7%. Those are the two low-season windows (Apr-Jun and Jul-Sep, Southern
Hemisphere winter; `03_granularity_baselines` documented the Dec-Mar peak /
Jun-Aug trough). Window 3 flips from under-forecasting by 10,565 units to
over-forecasting by 4,011.

The reading: a single smearing factor is estimated across the whole training
panel and applied uniformly, so it scales peak and trough alike. The correction
is sized for the average week, which over-corrects the quiet ones. A
season-specific (or segment-specific) smearing factor is the obvious follow-up,
untested here.

Note the two metrics disagree on purpose, and both are reported per the protocol:
per-series RMSE and bias improve while portfolio WAPE worsens in two windows.
WAPE is dominated by the high-volume series and windows; RMSE mean weights every
series equally. Reporting only one of them would have hidden half of what
happened.

## 3. Where this model is actually usable

At category x location the smearing run reaches 11.4% WAPE in window 2 and stays
between 26% and 39% elsewhere — the same conclusion
`08_decision_horizon_and_product_axis` reached from a different direction
(SKU-level error is not actionable; category-level error is). Both levels come
from summing the *same* predictions, so this is not a second model, it is the
same one measured at the grain the business can act on.

## 4. Caveats a reviewer should know

- **Actual demand differs from the baseline's.** Total demand per window in PROD is
  0.55%-1.67% higher than when `09_baseline_close_out` computed the baseline —
  verified with three queries: `date_id` and `date(placed_at)` agree exactly, and this
  scratch table matches PROD exactly, so the difference is in PROD itself (retroactive
  orders arriving through ingestion). `evaluate.py`'s 0.5% tolerance warning fires on
  every run above, correctly. It does not change the ranking here (the gaps are
  8-44pp); re-running the baseline on the current snapshot would remove it.
- **Target definition.** This run trains and scores on `qty_sold_gross`
  (`quantity` on `paid`/`confirmed` orders), matching the baseline's own
  definition. Stage 2's `load_weekly_panel()` uses `qty_sold_net`.
- **Window boundaries.** The 91-day window is exactly `cutoff+1` to `cutoff+91`.
  Weekly predictions are prorated by how many of each week's days fall inside it
  (`pred_week * days_inside / 7`), verified to sum to exactly 91 days in all four
  windows.
- **No trend-free variant.** `10_frozen_feature_set.md` rules out "no trend handling"
  as a valid state, so it is not tested as an option.

## 5. What would be worth trying next

1. A season- or segment-specific smearing factor, since the single global factor
   over-corrects the low season.
2. Dropping the log transform entirely (fit on raw counts, or a Poisson/negative
   binomial GLM) — the retransformation problem disappears rather than being
   corrected after the fact.
3. Reporting the category level as the headline for the client-facing decision,
   with SKU level kept as the honest accuracy statement.
