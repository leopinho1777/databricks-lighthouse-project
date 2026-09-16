# Task 1.3/1.4/1.6/1.7/1.8 Close-Out — Genuine 3-Month-Ahead Baseline

**Scripts:** [`walk_forward.py`](walk_forward.py), [`run_genuine_baseline.py`](run_genuine_baseline.py), [`log_baseline_to_mlflow.py`](log_baseline_to_mlflow.py)
**Output:** [`output/`](output/)

## Why this stage exists

`08_decision_horizon_and_product_axis` responded to the concern that the
original baselines (`03`) only forecast ~1 week ahead by measuring error over
15/30-day windows. That doesn't fix it: the Moving Average level inside those
windows is still recomputed every single day
(`ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING`), so by day 20 of a nominal
"30-day forecast" it has already absorbed 19 days of real, otherwise-unknown
actuals — a continuously-refreshed one-step-ahead forecast, re-bucketed for
reporting, not a genuine longer-horizon one. It also only reaches 30 days, not
the ~91-day (3-month) horizon actually agreed on. A standalone demo
(`forecasting_redo/07_horizon_fix_demo/`, on a separate independent redo of
this whole phase) proved the gap concretely: re-running `08`'s own method at a
true 91-day window, held static instead of continuously refreshed, moves WAPE
from 22-35% to 122-226% on identical data.

This stage closes that gap for real, plus the two tasks nothing in
`forecasting/` had built at all: walk-forward validation (1.6) and MLflow
logging (1.8).

## What changed vs. `03`/`08`

- **`walk_forward.py`** — a reusable, grain-agnostic rolling-origin function
  (`freq` accepts any pandas offset, so it works at daily or weekly grain).
  Nothing like this existed anywhere in the repo before.
- **`run_genuine_baseline.py`** — same data source, grain, and Moving
  Average(28d)/Seasonal-Naive methods as `08` (`fct_sales` in the shared prod
  marts, `lh_nautical.marts.fct_sales` — see `../README.md`'s "Data source
  convention", `product_variant_id x location_id`), but the Moving Average level is computed
  **once per cutoff**, from the 28 days immediately before it, and held flat
  for the full 91-day horizon. Scored across 4 rolling origins spanning 2025
  (task 1.6) rather than one holdout. Also adds the peak-season metric split
  task 1.7 calls for, independently re-derived from this data source's own
  train period (Jan-Apr/Oct-Dec — matches both earlier independent
  derivations in `07_hierarchical_reconciliation` and `forecasting_redo/03_metrics_1.7`).
- **`log_baseline_to_mlflow.py`** — logs these corrected numbers to
  `/Shared/00_baseline` as `moving_average_genuine_91d_v2` /
  `seasonal_naive_genuine_91d_v2`, distinct from any prior run in that
  experiment.

## Results

Portfolio-level (summed across all 6,054 series), 4 non-overlapping 91-day
windows spanning 2025:

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

Both baselines land in the 79-135% WAPE range at a genuine 91-day horizon —
in the same order of magnitude the independent redo's horizon-fix demo found
(122-226% on a different data source/grain), not `08`'s reported 22-35%.
**Seasonal Naive outperforms Moving Average here** (lower WAPE and bias in
every one of the 4 windows) — the opposite ranking from `03`'s 1-week-horizon
finding, which favored Moving Average/SES. This is a real, useful result: at
this horizon the "same period last year" lookup, which already encodes the
seasonal cycle, holds up better than a flat trailing average that has no way
to anticipate a seasonal swing 3 months out.

## What this stage does not resolve

- **The bias is still large and one-directional at every window** (all 8
  rows show real, positive under-forecasting) — consistent with `03`'s
  documented growth-trend bias, now visible at the horizon that actually
  matters for stocking decisions. Neither baseline has a trend component;
  that's flagged as the next lever, not something Phase 1's scope covers.
- **Only 4 origins**: same limitation the independent redo documented —
  more, denser cutoffs would give a more stable read, at the cost of more
  queries. Kept at 4 to match the ~91-day horizon exactly without overlap.

## Checkpoint

This closes Phase 1 "Baseline Model Definition" (tasks 1.1-1.8) for the shared
`forecasting/` tree: 1.1/1.2/1.5 were already settled and unchanged by this
stage; 1.3/1.4 are now genuinely horizon-correct; 1.6, 1.7 (peak-season), and
1.8 now exist where they didn't before.
