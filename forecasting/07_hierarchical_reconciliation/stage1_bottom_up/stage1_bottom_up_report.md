# Hierarchical Reconciliation — Stage 1: Bottom-Up

Sums `06_multi_grain`'s per-series recommended forecast (the better of `05`'s
native daily SBA or `06`'s ADIDA, chosen per series) across all 6 locations
to produce a national forecast per product — Bottom-Up's defining trait: no
separate national-level model, just summation. Produced by
[`run_stage1_bottom_up.py`](run_stage1_bottom_up.py); per-product metrics in
[`output/bottom_up_national_metrics.csv`](output/bottom_up_national_metrics.csv),
whole-catalog portfolio total in
[`output/bottom_up_portfolio_metrics.csv`](output/bottom_up_portfolio_metrics.csv).

## Method

- **Input:** `06`'s committed per-series/per-day forecast cache
  (`06_multi_grain/output/_recommended_forecasts.parquet`), loaded directly —
  same reuse-in-place convention `04` used for `03`'s cache and `06` used for
  `05`'s. No new Databricks query.
- **Aggregation:** group by (`product_variant_id`, `period`), sum
  `qty_sold_net` (actual) and `recommended_pred` (forecast) across all 6
  locations. A product/period is excluded from the sum only if *every*
  location's forecast is still `NaN` (pre-trim start-up); a partial set of
  reporting locations is summed as-is (`skipna=True`) rather than zeroed out.
  Only 15,563 of 2,446,831 product/period rows (0.6%) have any location still
  in start-up — negligible.
- **Metrics:** `most_recent_complete_year`/`compute_metrics` reused verbatim
  from `03`, same holdout year (2025), computed **on the summed national
  series directly** — never by averaging per-location metrics, since error
  aggregation and value aggregation behave differently (summing forecasts
  first, then scoring the sum, is not the same as scoring each location and
  averaging the scores).

## Results — per-product national metrics (n=1,009 products)

| metric | mean | median |
|---|---|---|
| RMSE | 1.553 | 1.547 |
| Bias | -0.0086 | — |
| MAPE (zero-excluded) | 89.8% | 90.0% |
| sMAPE | 197.9% | 197.9% |

## Results — whole-catalog portfolio total (all 1,009 products × 6 locations summed per day)

| rmse | bias | mape | smape |
|---|---|---|---|
| 174.27 | -8.70 | 0.691 | 0.464 |

This is nearly identical to `05`'s/`06`'s own whole-portfolio totals for SBA
(RMSE 174.48-174.5, bias -11.5, smape 0.464) — expected, since summing across
locations-then-products is associative with summing across all 6,054 series
directly; the tiny difference is exactly the ~55% of series `06` routed to
ADIDA instead of native SBA. This agreement is a useful sanity check that the
aggregation code is correct, not a new finding in its own right.

## Discussion

**National aggregation reduces zero-actual sparsity, but far less dramatically
than Section 1's hypothesis suggested — and the reference point matters.**
In the 2025 holdout year specifically, the average product×location series is
zero-actual on **98.95%** of days, while the same products' *national*
(location-summed) series are zero-actual on **93.90%** of days (median 94.0%,
range 90.1%-97.5% across products). That is a real reduction — aggregating
across locations does help, as hypothesized — but the national series is
still overwhelmingly zero on any given day, not remotely close to Smooth.
Note this 98.95%/93.90% pair is **not the same reference point** as the
73.1% zero-actual figure quoted in `01`/`04`'s Phase 1 findings — that number
was computed over the full 2020-2025 history, while this stage's numbers are
restricted to the 2025 holdout year alone (a materially sparser slice, per
the per-product `n_forecastable_rows`/`pct_forecastable` columns in the
output CSV — worth flagging for whoever reconciles these numbers later
rather than treating 73% and 94%/99% as directly comparable).

**Per-product RMSE scales roughly like independent-error aggregation, not
like fully correlated or fully cancelling errors.** `05`/`06`'s per-location
RMSE mean was 0.594. If forecast errors across a product's 6 locations were
perfectly correlated (all high or all low together), summing would scale
RMSE roughly linearly (~6 × 0.594 ≈ 3.56). If they were independent, RMSE
would scale like `√6 × 0.594 ≈ 1.455`. The observed national per-product RMSE
mean (1.553) sits close to the independent-error estimate, slightly above
it — consistent with per-location demand shocks for the same product being
largely idiosyncratic to each location rather than synchronized, with no
strong evidence of either amplification or cancellation. Bias, being linear
by construction, scales as expected regardless of correlation: national bias
mean (-0.0086) falls inside the range implied by 6× the per-location bias
means from `05`/`06` (-0.0072 to -0.0114).

**sMAPE/MAPE remain structurally uninformative at national grain, for the
same reason as `05`/`06`.** With ~94% of national-series days still
zero-actual and the underlying forecasts (SBA/ADIDA) essentially never
landing on exact zero, sMAPE saturates near its analytic maximum again
(median 197.9%) and MAPE stays pinned near 90%. **RMSE and Bias remain the
metrics to trust** when Stage 3 compares Bottom-Up against Top-Down.

## Checkpoint

Stopping here per the project's step-by-step review requirement (same
convention as `01`-`06` and the hierarchical-reconciliation plan itself).
Stage 2 (Top-Down) is designed in the plan but not yet implemented — pending
review of the findings above, in particular the sparsity-reference-point
caveat (94%/99% here vs. 73% in Phase 1) and the near-independent-error RMSE
scaling, both of which should carry into Stage 3's comparison discussion.
