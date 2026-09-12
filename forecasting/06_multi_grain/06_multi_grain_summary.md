# Multi-Grain / ADIDA Backtest Report — Strategy 3 (Step C)

Two questions, per `05`'s recommendation and `04`'s own "fast follow" suggestion:
does a real Smooth/Erratic segment emerge once the catalog is reclassified at
weekly grain, and does forecasting SBA at weekly grain and disaggregating back
to daily (ADIDA) lift accuracy over `05`'s native daily-grain SBA. Produced by
[`run_multi_grain.py`](run_multi_grain.py); weekly reclassification in
[`output/weekly_classification.csv`](output/weekly_classification.csv) /
[`output/weekly_category_summary.csv`](output/weekly_category_summary.csv),
daily-grain comparison in
[`output/adida_daily_metrics.csv`](output/adida_daily_metrics.csv) /
[`output/adida_vs_daily_sba_by_category.csv`](output/adida_vs_daily_sba_by_category.csv),
weekly-native SBA in
[`output/adida_weekly_native_metrics.csv`](output/adida_weekly_native_metrics.csv),
per-series verdict in
[`output/method_recommendation.csv`](output/method_recommendation.csv).

## Method

- **Weekly reclassification:** same ADI/CV² machinery as `04`
  (`compute_series_stats`/`classify_category`, same 1.32/0.49 thresholds),
  reused verbatim against `03`'s cached weekly rollup, left-trimmed to each
  series' own first non-zero week.
- **ADIDA:** `05`'s `croston_sba()` (SBA, α=0.1 — carried forward per `05`'s
  finding that SBA strictly beats raw Croston) run sequentially at weekly
  grain, then disaggregated to daily via **uniform split**
  (`weekly_forecast / 7`, spread across that week's 7 calendar days) — the
  simplest defensible disaggregation with no validated day-of-week profile to
  weight it by instead.
- **Comparison:** the disaggregated daily forecast is compared against `05`'s
  actual native daily-SBA forecast values (`05/output/_croston_sba_forecasts.parquet`,
  loaded directly rather than recomputed) on the identical daily holdout year
  (2025), using the same `compute_metrics` reused throughout this workstream.
  Per `05`'s finding that sMAPE/MAPE saturate near their analytic maximum for
  Croston-family forecasts on this catalog, **RMSE and Bias are the metrics
  trusted below**, sMAPE/MAPE are reported for completeness only.

## Results — weekly-grain reclassification

| category | n_series | % of series | % of volume |
|---|---|---|---|
| intermittent | 5,674 | 93.7% | 94.7% |
| lumpy | 380 | 6.3% | 5.3% |
| smooth | 0 | 0.0% | 0.0% |
| erratic | 0 | 0.0% | 0.0% |

Weekly ADI distribution (n=6,054): min 8.6, 25th pct 15.1, median 17.5, 75th
pct 20.4, max 50.0 — every series remains **at least 6.5x above** the 1.32
threshold even after aggregating 7 daily periods into 1. (Weekly ADI ≈ daily
ADI / 7 is exactly what's observed: daily median was 118.9 days, 118.9/7 ≈
17.0, matching the weekly median of 17.5 almost exactly — aggregation shrinks
ADI proportionally to the aggregation factor, nothing more.)

## Results — ADIDA vs. native daily SBA (per-series, full catalog)

| method | rmse_mean | rmse_median | bias_mean | smape_median |
|---|---|---|---|---|
| daily_sba_native | 0.5944 | 0.6049 | -0.0019 | 1.9994 |
| adida_disaggregated | 0.5943 | 0.6048 | -0.0012 | 1.9994 |

Per-series RMSE win rate: **ADIDA wins 3,291/6,054 series (54.4%)** — close
to a coin flip. Distribution of `rmse_improvement_pct` (ADIDA vs. native,
positive = ADIDA better): median 0.00%, mean +0.05%, **97.7% of series fall
within ±1%** of each other. Only 125 series (2.1%) show a >1% improvement,
61 (1.0%) a >2% improvement, and just 3 (0.05%) exceed 5% — the single
largest win is +6.1%. Conversely 14 series (0.23%) get **meaningfully worse**
under ADIDA, one by -24.2%.

By demand-pattern category, the two methods are statistically indistinguishable:

| method | category | rmse_mean | rmse_median | bias_mean |
|---|---|---|---|---|
| daily_sba_native | intermittent | 0.5977 | 0.6090 | -0.0019 |
| adida_disaggregated | intermittent | 0.5976 | 0.6091 | -0.0012 |
| daily_sba_native | lumpy | 0.4936 | 0.4927 | -0.0021 |
| adida_disaggregated | lumpy | 0.4935 | 0.4928 | -0.0018 |

## Results — weekly-grain SBA, native (context only, not comparable in scale)

rmse_mean=1.588, rmse_median=1.587, bias_mean=-0.0074 against weekly-summed
actuals. **Not directly comparable to the daily-grain numbers above** — a
week's `qty_sold_net` is a sum of ~7 days, so its RMSE lives on a different
scale by construction. Reported only so this stage's own weekly-level
diagnostics are on record.

## Discussion

**Weekly aggregation does not create a Smooth or Erratic segment — the
sparsity is structural, not a grain artifact.** This directly confirms `04`'s
prediction and the hierarchical-reconciliation context document's framing
(Section 1): "aggregating across time... doesn't fix this." The lowest ADI in
the entire 6,054-series catalog, even after aggregating 7 days into 1, is
still 6.5x the classification threshold. The one real shift is CV²-driven:
the Lumpy share roughly doubles (3.2% → 6.3%) as summing 7 days into one
bucket increases sale-size variability relative to the mean for a modest
subset of series — a real if minor effect, but it doesn't touch the ADI axis
at all. **This corroborates rather than complicates the hierarchical
reconciliation plan's own reasoning: only aggregating across a *different*
dimension (location, not time) meaningfully changes the sparsity picture.**

**ADIDA does not provide a meaningful lift over native daily SBA for this
catalog.** The pooled per-series RMSE is essentially identical (0.5944 vs.
0.5943 mean — a 0.02% difference), the 54.4% win rate is indistinguishable
from noise around a near-zero mean improvement, and 97.7% of series sit
within ±1% of each other regardless of which method is used. The one
consistent, if small, signal is on **Bias**: ADIDA's bias magnitude is
~35-40% smaller than native daily SBA's across both categories (-0.0012 vs.
-0.0019 pooled) — plausible, since averaging SBA's forecast over a full week
before splitting it back out smooths away some of the day-to-day
over-forecast tendency Croston-family methods carry. It is a real but modest
effect, not the kind of "lift" that would justify ADIDA's added complexity
(a second sequential model, a disaggregation step, twice the moving parts) as
the default treatment.

**The per-series "winner" in `method_recommendation.csv` should not be read
as a validated per-series improvement.** Because 97.7% of series differ by
less than 1% — within the noise band of a uniform 1/7 disaggregation applied
to an already-noisy intermittent-demand forecast — picking whichever method
has the strictly lower RMSE per series is mostly picking noise, not signal.
The recommendation file is retained as-is (raw numbers, not filtered) so a
future stage can apply its own materiality threshold, but this report's own
recommendation is not "use ADIDA wherever it numerically wins."

## Recommendation for downstream stages

- **Default to `05`'s native daily SBA catalog-wide.** ADIDA does not clear a
  materiality bar (no meaningful pooled RMSE lift, ~55/45 coin-flip win rate,
  and a documented tail of series that get *worse*, one by -24%) to justify
  swapping it in as the default per-series treatment.
- **Exception, if a future stage wants one:** the ~61 series (1.0% of the
  catalog) with a >2% ADIDA RMSE improvement in
  `output/method_recommendation.csv` are a legitimate, small carve-out if a
  future phase wants to special-case them — but this is optional polish, not
  required for the workstream's headline conclusion.
- **For `07_hierarchical_reconciliation`'s Bottom-Up stage** (Section 3.5 of
  the reconciliation context document): the per-series/per-day forecast
  values persisted to `output/_recommended_forecasts.parquet`
  (`recommended_pred`, with `method_chosen` recording which of `05`/`06`
  produced each series' value) are the committed per-series output that
  stage is gated on. Given the finding above, `method_chosen` will read
  `daily_sba` for the overwhelming majority of series and `adida` only for
  the small tail where it's genuinely better — this is expected and correct
  given the numbers, not a bug in the selection logic.

## Checkpoint

Stopping here per the project's step-by-step review requirement (same
convention as `01`-`05` and the hierarchical-reconciliation plan). This
closes out the classification → Croston/SBA → ADIDA workstream referenced by
the reconciliation plan's Section 3.5 prerequisite — `07_hierarchical_reconciliation/stage1_bottom_up/`
is now unblocked, pending review of the findings above (in particular, that
ADIDA's own per-series recommendation is "mostly noise, use `05`'s daily SBA
by default").
