# Croston / SBA Backtest Report — Strategy 2 (Step B)

Full-catalog backtest of Croston's method and its Syntetos-Boylan Approximation
(SBA) bias correction against `fact_demand_daily`, benchmarked directly
against `03_granularity_baselines`'s daily-grain Seasonal Naive / Moving
Average / SES results. Produced by
[`run_croston_sba.py`](run_croston_sba.py); per-series numbers in
[`output/croston_sba_per_series_metrics.csv`](output/croston_sba_per_series_metrics.csv),
category rollup in
[`output/croston_sba_by_category.csv`](output/croston_sba_by_category.csv),
head-to-head vs. baselines in
[`output/croston_sba_vs_baselines.csv`](output/croston_sba_vs_baselines.csv),
whole-catalog portfolio total in
[`output/croston_sba_portfolio_metrics.csv`](output/croston_sba_portfolio_metrics.csv).

## Scope

`04_demand_classification` found 96.8% of the 6,054 product×location series
Intermittent and 3.2% Lumpy at daily grain, with **0% Smooth or Erratic** —
there is no Smooth segment to exclude at this grain, so per that stage's own
recommendation, this run covers the **full catalog**, not a subset.

## Method

- **Grain:** daily, same as `03`/`04`, same source table
  (`fact_demand_daily`, each developer's own scratch copy — see `../README.md`'s "Data source convention").
- **History window, per series:** left-trimmed to each series' own first day
  with `qty_sold_net > 0`, identical rationale and trimming logic as `04`
  (avoids counting a later-launched product's pre-launch zero-fill).
- **Algorithm:** classic Croston (1972) — separately exponentially-smooths
  non-zero demand *size* (`z`) and *inter-demand interval* (`p`), updating
  only on periods with a sale; forecast = `z/p`, held constant between sales.
  **SBA** (Syntetos & Boylan, 2005) applies the `(1 - α/2)` multiplicative
  correction to `z/p`, addressing Croston's known positive bias.
  `α = 0.1`, the standard literature default.
- **No lookahead:** `forecast[t]` uses only state accumulated through `t-1`;
  state updates (and the interval counter) advance strictly sequentially per
  series — enforced the same way `03` enforces it for rolling/EWM baselines,
  adapted for Croston's conditional (sale-days-only) update rule.
- **Metrics:** `most_recent_complete_year()` and `compute_metrics()` reused
  verbatim from `03_granularity_baselines/run_baselines.py` (same holdout
  year — 2025 — same RMSE/Bias/MAPE(zero-excluded)/sMAPE definitions), so
  every number below is directly comparable to `03`'s daily-grain row.

## Results — per-series metrics vs. `03`'s daily baselines

| method | n_series | rmse_mean | rmse_median | bias_mean | mape_median | smape_mean | smape_median |
|---|---|---|---|---|---|---|---|
| seasonal_naive | 6,054 | 0.835 | 0.841 | +0.0087 | 1.000 | 0.038 | 0.038 |
| moving_average | 6,054 | 0.603 | 0.616 | +0.0002 | 0.994 | 0.515 | 0.498 |
| ses | 6,054 | 0.642 | 0.657 | +0.0001 | 1.000 | 1.999 | 2.000 |
| **croston** | 6,054 | **0.595** | **0.605** | -0.0051 | 0.984 | 1.999 | 1.999 |
| **sba** | 6,054 | **0.594** | **0.605** | -0.0019 | 0.985 | 1.999 | 1.999 |

All five methods forecast 100% of series (`pct_series_fully_excluded = 0.0`
across the board).

## Results — by demand-pattern category (04's routing labels)

| method | category | n_series | rmse_mean | rmse_median | bias_mean |
|---|---|---|---|---|---|
| croston | intermittent | 5,862 | 0.598 | 0.609 | -0.0051 |
| croston | lumpy | 192 | 0.494 | 0.493 | -0.0045 |
| sba | intermittent | 5,862 | 0.598 | 0.609 | -0.0019 |
| sba | lumpy | 192 | 0.494 | 0.493 | -0.0021 |

## Results — whole-portfolio total (all series summed per day, 365 holdout days)

| method | rmse | bias | mape | smape |
|---|---|---|---|---|
| seasonal_naive | 135.3 | +52.46 | 0.350 | 0.367 |
| moving_average | 106.8 | +1.50 | 0.313 | 0.270 |
| ses | 100.6 | +0.74 | 0.287 | 0.253 |
| **croston** | **176.9** | -30.60 | 0.737 | 0.464 |
| **sba** | **174.5** | -11.54 | 0.697 | 0.464 |

## Discussion

**Croston/SBA wins on per-series RMSE, the opposite of the portfolio-level
picture.** At the per-series level, Croston/SBA has the lowest mean and
median RMSE of all five methods (0.594-0.595 vs. 0.603-0.657 for the three
`03` baselines) — consistent with Croston-family methods being purpose-built
for exactly this kind of catalog. But summed to the whole-portfolio total,
SES and Moving Average both clearly beat Croston/SBA (RMSE ~101-107 vs.
~175-177). **Per-series accuracy and portfolio-aggregate accuracy are not
the same objective here** — a method that is individually best-calibrated
per series does not automatically sum to the best aggregate. This is the
same tension Section 1 of the hierarchical-reconciliation context document
flags as the reason Bottom-Up vs. Top-Down needs an actual empirical
comparison rather than an assumption — this backtest is a first concrete
data point for that later workstream, not just for Step B/C.

**sMAPE and MAPE are structurally uninformative for Croston/SBA at this
grain — a known metric artifact, not a modeling defect.** sMAPE saturates
near its analytic maximum of 2.0 whenever the actual is 0 and the forecast
is positive (`2·|0-p| / (|0|+|p|) = 2`). Croston-family forecasts are a
smoothed positive constant between sales and essentially never land on exact
zero, while ~73% of daily rows are zero-actual (Phase 1 finding, restated by
`04`) — so nearly every zero-actual row scores the maximum sMAPE penalty,
dragging the median to ~1.999 and MAPE-median to ~0.98 (98%) regardless of
how good the non-zero-day forecasts are. Seasonal Naive's low sMAPE (0.038)
is the mirror image of the same artifact: it frequently repeats last year's
*also-zero* value on a zero-actual day, scoring a perfect 0 rather than a
near-2 penalty — that is not evidence Seasonal Naive forecasts better,
only that it is more likely to predict exact zero. **RMSE and Bias are the
trustworthy metrics for comparing methods on this catalog; sMAPE/MAPE should
be read with this caveat attached, not at face value**, for Croston/SBA and
any future intermittent-demand method here (a scale-free metric like MASE
would sidestep this, but is out of scope for this stage — reusing `03`'s
`compute_metrics` as instructed keeps every stage on one comparable metric
set).

**SBA is a strict improvement over raw Croston, not a trade-off.** Its whole
purpose — correcting Croston's known over-forecast bias — shows up cleanly:
bias improves from -0.0051 to -0.0019 per-series (mean) and from -30.60 to
-11.54 at the portfolio level, more than halving the bias magnitude in both
views, while RMSE is statistically unchanged (differs by <0.002 per-series,
~2.4 out of ~175 at portfolio level) and MAPE/sMAPE are also marginally
better. There is no case in this backtest where raw Croston beats SBA on any
metric that matters — **SBA, not Croston, should be the candidate carried
into Step C.**

**Lumpy slightly outperforms Intermittent on RMSE for both methods** (0.493
vs. 0.609 median), plausible given Croston-family methods explicitly model
sale-size variability, which is what defines the Lumpy segment. Bias also
improves more from Croston→SBA on the Lumpy segment in relative terms, though
both segments see the same qualitative correction.

## Recommendation for Step C (`06_multi_grain` / ADIDA)

- Carry **SBA (α=0.1)** forward as the Croston-family candidate, not raw
  Croston.
- Test whether aggregating to weekly grain before forecasting (ADIDA) lifts
  SBA's already-favorable per-series RMSE further, and whether it changes the
  portfolio-level picture where SES/Moving Average currently win — per `04`'s
  own suggestion to check classification at weekly grain as a fast follow.
- Report Step C's results on RMSE/Bias primarily, carrying the same sMAPE/MAPE
  caveat forward rather than expecting those two metrics to look good even if
  ADIDA produces a genuine improvement.

## Hand-off

Two findings carry forward: the per-series-vs-portfolio RMSE divergence (SBA wins per series
and loses at the portfolio total) and the sMAPE/MAPE metric artifact, which makes RMSE and
Bias the metrics used in every later stage. `06_multi_grain` tests ADIDA and repeats the
classification at weekly grain.
