# Task 1.3/1.4/1.6/1.7/1.8 Close-Out — 3-Month-Ahead Baseline (Held Static)

**Scripts:** [`walk_forward.py`](walk_forward.py), [`run_genuine_baseline.py`](run_genuine_baseline.py), [`log_baseline_to_mlflow.py`](log_baseline_to_mlflow.py)
**Output:** [`output/`](output/)

## What this stage defines

The baseline every later model is measured against: a forecast made **once at a cutoff**
from data up to that cutoff and **held static** for the full ~91-day (3-month) horizon the
project agreed on (task 1.2), scored across four rolling origins spanning 2025 (task 1.6),
with a peak-season split (task 1.7), and logged to MLflow (task 1.8).

**Why the forecast is held static.** A forecast that is recomputed as time passes (for
example a trailing 28-day average with `ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING`) absorbs
real actuals from inside the window it is scored against: by day 20 of a nominal "30-day
forecast" it has already seen 19 days of otherwise-unknown demand, so it is a one-step-ahead
forecast re-bucketed into windows, not a longer-horizon one. `08_decision_horizon_and_product_axis`
measures error over 15/30-day windows of that kind (its Moving Average is recomputed daily), so its
WAPE figures are one-step-ahead errors re-bucketed into windows and are **not comparable** with the
91-day held-static numbers below. Holding the level
flat for the whole horizon removes that leakage, which is why the numbers below are the ones
that correspond to the horizon the business plans on. Every Stage 3 model is scored the same
way (`../experiments/_shared/evaluate.py`).

## Components

- **`walk_forward.py`** — a reusable, grain-agnostic rolling-origin function (`freq`
  accepts any pandas offset, so it works at daily or weekly grain). `evaluate.py` imports
  `make_periodic_cutoffs()` from it, so the baseline and every Stage 3 model share the same
  four cutoffs.
- **`run_genuine_baseline.py`** — reads `fct_sales` from the shared prod marts
  (`lh_nautical.marts.fct_sales`, orders in `paid`/`confirmed` status; see `../README.md`'s
  "Data source convention"), at `product_variant_id x location_id` grain. Two methods:
  Moving Average (28d), whose level is computed **once per cutoff** from the 28 days
  immediately before it and held flat for the 91-day horizon; and Seasonal Naive, which
  joins on the same calendar dates one year earlier. Scored across the 4 rolling origins,
  with the peak-season metric split derived from this data source's own train period
  (Jan-Apr/Oct-Dec, matching the derivation in `07_hierarchical_reconciliation`).
- **`log_baseline_to_mlflow.py`** — logs the results to `/Shared/00_baseline` as
  `moving_average_genuine_91d_v2` / `seasonal_naive_genuine_91d_v2`. The Seasonal Naive run is
  the champion every Stage 3 experiment is compared against.

## Results

Portfolio-level, 4 non-overlapping 91-day windows spanning 2025:

| cutoff | baseline | actual | forecast | bias | WAPE |
|---|---|---:|---:|---:|---:|
| 2024-12-31 | moving_average | 45,909 | 31,356 | 14,553 | 114.2% |
| 2025-04-01 | moving_average | 23,007 | 21,866 | 1,141 | 134.9% |
| 2025-07-01 | moving_average | 17,069 | 5,837 | 11,232 | 109.6% |
| 2025-09-30 | moving_average | 40,968 | 15,451 | 25,518 | 107.7% |
| 2024-12-31 | seasonal_naive | 45,909 | 29,923 | 15,986 | 78.8% |
| 2025-04-01 | seasonal_naive | 23,007 | 10,100 | 12,907 | 84.4% |
| 2025-07-01 | seasonal_naive | 17,069 | 5,619 | 11,450 | 88.1% |
| 2025-09-30 | seasonal_naive | 40,968 | 24,725 | 16,243 | 79.9% |

Both baselines land in the 79-135% WAPE range at the 91-day horizon.
**Seasonal Naive outperforms Moving Average** (lower WAPE and bias in every one of the 4
windows) — the opposite ranking from `03`'s 1-week-horizon finding, which favored Moving
Average/SES. At this horizon the "same period last year" lookup, which already encodes the
seasonal cycle, holds up better than a flat trailing average that has no way to anticipate a
seasonal swing 3 months out.

## Scoring convention

WAPE, forecast totals and per-series metrics are computed over the series that have sales in
the window (the actuals query returns only those series; the forecast is merged onto them).
Forecast placed on a series with no sales in the window is therefore not scored here, and the
per-series averages in `output/genuine_baseline_metrics_overall.csv` are means over
(series, window) groups with `n = 1` each. `../experiments/_shared/evaluate.py` scores all 6,054
series in every window, so a model's WAPE and this baseline's WAPE differ in coverage; the
consequences are set out in `../11_model_comparison/11_model_comparison_report.md`.

## Limitations

- **The bias is large and one-directional at every window** (all 8 rows show positive
  under-forecasting) — consistent with `03`'s documented growth-trend bias, visible at the
  horizon that matters for stocking decisions. Neither baseline has a trend component; a
  trend-adjusted Seasonal Naive is the natural next reference.
- **Only 4 origins.** More, denser cutoffs would give a more stable read at the cost of more
  queries. Four is chosen to match the ~91-day horizon exactly without overlap.

## Scope

This stage completes Phase 1 "Baseline Model Definition" (tasks 1.1-1.8) for the shared
`forecasting/` tree: 1.1/1.2/1.5 (forecasting unit, horizon, split) are set by `02`/`03`, and
1.3/1.4 (Moving Average and Seasonal Naive baselines at the 91-day horizon), 1.6 (walk-forward
validation), 1.7 (peak-season metrics) and 1.8 (MLflow logging) are defined here.
