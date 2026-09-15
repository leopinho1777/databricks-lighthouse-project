# Demand Pattern Classification Report — Strategy 1

Full-catalog classification (all 6,054 product x location series in `fact_demand_daily`, no sampling) into the standard Syntetos-Boylan-Croston (SBC) demand-pattern quadrants — Smooth / Intermittent / Erratic / Lumpy — using ADI (average inter-demand interval) and CV² (squared coefficient of variation of sale size). Produced by [`classify_demand_patterns.py`](classify_demand_patterns.py); raw per-series numbers in [`output/demand_classification.csv`](output/demand_classification.csv), category rollup in [`output/category_summary.csv`](output/category_summary.csv).

This is the routing step for Strategy 2 (Croston/SBA on non-smooth segments) and Strategy 3 (multi-grain aggregation).

## Method

- **Grain:** daily — the native grain of `fact_demand_daily`, and the grain at which Phase 1 (`03_granularity_comparison_report.md`) found the catalog dominated by zero-actual days (73.1% at daily grain). Classifying at daily grain is what actually surfaces that intermittency; summing to weekly/monthly first would mask it.
- **History window, per series:** left-trimmed to each series' own first day with `qty_sold_net > 0`, through the last available day. `fact_demand_daily`'s zero-fill spine starts from one *global* `min(placed_at)` across the whole catalog rather than each product's own launch date (flagged in `02_ideal_schema_proposal.md`) — trimming avoids counting a later-launched product's pre-launch zero-fill as "intermittency" it never had a chance to break.
- **ADI** = (trimmed series length in days) / (count of days with a sale). **CV²** = variance of sale-day quantity / (mean sale-day quantity)², computed only over the days a sale actually occurred (sample variance, so at least 2 sale-day observations are required — series with only 0 or 1 sale-day observation after trimming are called out separately as `insufficient_data` rather than forced into a quadrant).
- **Thresholds:** the standard starting values, ADI = 1.32 and CV² = 0.49 (Syntetos & Boylan, 2005). Treated as a starting guideline per the task brief, not a hard rule — see Discussion below.

## Results

| category | n_series | % of series | total qty (net) | % of volume |
|---|---|---|---|---|
| intermittent | 5,862 | 96.8% | 630,273 | 97.7% |
| lumpy | 192 | 3.2% | 14,952 | 2.3% |
| smooth | 0 | 0.0% | 0 | 0.0% |
| erratic | 0 | 0.0% | 0 | 0.0% |
| insufficient_data | 0 | 0.0% | 0 | 0.0% |

`insufficient_data` is empty — every one of the 6,054 series had at least 2 sale-day observations after trimming (median 19 sale-days, minimum 6), so the catalog has enough history for CV² to be well-defined everywhere.

**Underlying ADI/CV² distribution** (from `demand_classification.csv`, n=6,054):

| stat | ADI (days) | CV² |
|---|---|---|
| min | 60.1 | 0.045 |
| 25th pct | 102.8 | 0.223 |
| median | 118.9 | 0.281 |
| 75th pct | 138.8 | 0.347 |
| 95th pct | — | 0.464 |
| max | 348.7 | 0.869 |

## Discussion — the 1.32 ADI threshold does not apply at this grain

**Every single series has ADI ≥ 60 days — the *lowest* ADI in the entire 6,054-series catalog is ~45x the 1.32-day threshold.** Zero series land as Smooth or Erratic; the split between Intermittent and Lumpy is driven entirely by CV² (the ADI test never binds). This is exactly the calibration failure mode the task brief flagged in advance (per the Kostenko & Hyndman caveat): the 1.32/0.49 thresholds come from Syntetos & Boylan's original spare-parts inventory literature, where "demand periods" are typically weekly or monthly review cycles for slow-moving industrial parts. Applied here to *daily* retail transactions across a 1,009-SKU x 6-location catalog, a typical series only sells on ~19 of ~2,355 available days (well under 1% of days) — so almost nothing in a catalog like this can ever be "smooth" by a threshold calibrated for a review cycle roughly 45-260x coarser than a single day.

**This is a real, useful finding, not a broken classification:** it quantitatively confirms Phase 1's qualitative read of daily grain as "an intermittent-demand catalog" (73.1% zero-actual rows) and gives it a concrete number (ADI 60-349 days at the series level) instead of a single pooled statistic. But it also means the ADI axis is not currently doing any discriminating work — CV² alone is deciding Intermittent vs. Lumpy, and the four-quadrant framework is effectively collapsed to two categories at this grain.

**What this implies for Strategy 2/3, not yet acted on here:**
- Because every series is non-smooth by these thresholds, **the entire 6,054-series catalog is in scope for Croston/SBA** in Step B, not a subset — there is no Smooth segment to exclude at daily grain under the standard thresholds. This should be flagged back to the team: it may mean either (a) Croston/SBA genuinely benefits the whole catalog at daily grain, or (b) the ADI threshold needs local recalibration (e.g., against this catalog's own ADI distribution — the 25th percentile here, ~103 days, could plausibly serve as a catalog-relative "smooth" cutoff instead of the literature's 1.32) before the classification is used to gate treatment rather than just describe the catalog.
- The CV² split (96.8% Intermittent / 3.2% Lumpy) looks more usable as-is: it's not collapsed to one bucket, and the 3.2% Lumpy tail sits above the 95th percentile of the CV² distribution, which is a defensible "erratic sale-size" cutoff regardless of the ADI question.
- **Recommendation for Step B:** proceed with Croston/SBA against all Intermittent + Lumpy series (i.e., effectively the full catalog at daily grain) as the task brief specifies, but carry this ADI-threshold caveat into the write-up rather than treating the 1.32 boundary as validated at this grain. Step C's ADIDA test (aggregating to weekly before forecasting) is also a natural place to revisit whether a coarser grain brings ADI back into a range where the standard thresholds discriminate meaningfully — worth checking classification at weekly grain too as a fast follow, once Step B's results are in.

## Checkpoint

Stopping here per the task's step-by-step review requirement. Step B (Croston/SBA backtest for the Intermittent/Lumpy segments) is designed in the plan but not yet implemented — pending review of the breakdown above, in particular the ADI-threshold finding and its implication that the entire catalog falls outside the Smooth segment at daily grain.
