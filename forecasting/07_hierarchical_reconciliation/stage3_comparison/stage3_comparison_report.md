# Hierarchical Reconciliation — Stage 3: Bottom-Up vs. Top-Down Comparison

Direct comparison of Stage 1 (Bottom-Up) and Stage 2 (Top-Down) at the two
levels each already produces a forecast for: national (both) and location
(Bottom-Up native vs. Top-Down disaggregated). Produced by
[`run_stage3_comparison.py`](run_stage3_comparison.py); headline numbers in
[`output/method_comparison.csv`](output/method_comparison.csv), full detail
in
[`output/national_comparison_detail.csv`](output/national_comparison_detail.csv) /
[`output/location_comparison_detail.csv`](output/location_comparison_detail.csv) /
[`output/location_comparison_by_category.csv`](output/location_comparison_by_category.csv),
seasonal bias comparison in
[`output/seasonal_bias_comparison.csv`](output/seasonal_bias_comparison.csv).

## Method

- **National comparison:** Stage 1's per-product `bottom_up_national_metrics.csv`
  vs. Stage 2's per-product `top_down_national_metrics.csv` (filtered to the
  `top_down_routed` row — i.e. SBA, since Stage 2 found 100% of products
  route there). Portfolio-level Top-Down total is derived here (not already
  in Stage 2's output) by reusing Stage 2's own `route_forecast` against its
  cached national-forecast parquet — no new forecasting logic.
- **Location comparison:** Bottom-Up's *native* per-series forecast —
  reconstructed by joining `06`'s tracked `adida_daily_metrics.csv` (full
  metrics for both `daily_sba_native` and `adida_disaggregated`) against
  `06`'s `method_recommendation.csv` (`method_chosen` per series) to pick out
  each series' actually-recommended row, no rerun needed — vs. Stage 2's
  `top_down_location_metrics.csv` (national forecast × static location
  share).
- **Win rate:** per-product/per-series, whichever method has the strictly
  lower RMSE (the metric this workstream has trusted since `05`'s
  sMAPE/MAPE-saturation finding).

## Results — national level (n=1,009 products)

| method | rmse_mean | rmse_median | bias_mean | % of products winning RMSE |
|---|---|---|---|---|
| **Bottom-Up** | 1.5528 | 1.5471 | -0.0086 | **80.4%** |
| Top-Down | 1.5554 | 1.5496 | +0.0248 | 19.6% |

Portfolio total (all 1,009 products summed per day, 365 holdout days):

| method | rmse | bias |
|---|---|---|
| **Bottom-Up** | **174.27** | -8.70 |
| Top-Down | 180.98 | +25.06 |

**Bottom-Up wins decisively at the national level** — the level Top-Down is
supposed to have the "home advantage" on, since it's fit directly there. Per
product it wins 80.4% of the time; at the portfolio level its RMSE is 3.7%
lower and its bias magnitude is **2.9x smaller** (-8.70 vs. +25.06).

### Why: both methods share the same underlying weakness, but Bottom-Up dilutes it

Both Bottom-Up and Top-Down are built on the *same* SBA (α=0.1) engine — Top-Down
fits one SBA model directly on the national aggregate; Bottom-Up fits SBA (or
ADIDA) independently per location and sums the results. `stage2`'s own report
already found SBA's slow-adapting smoothing constant badly lags this
catalog's seasonal cycle (high Jan-Apr/Oct-Dec, low May-Sep) when fit once on
the aggregate. The question here is whether summing 6 independently-lagged
local models fares any better:

| month | actual | Bottom-Up pred | BU bias | Top-Down pred | TD bias |
|---|---|---|---|---|---|
| Jan | 16,820 | 11,123 | +5,697 | 9,247 | **+7,573** |
| Jul | 4,356 | 11,285 | -6,929 | 10,312 | -5,956 |
| Nov | 14,877 | 10,524 | +4,353 | 8,715 | **+6,162** |
| **Total** | **127,961** | **131,138** | **-2.5% net** | **118,813** | **+7.1% net** |

Both methods lag the season in the same qualitative way (under-forecast in
high months, over-forecast in low months), and the **month-to-month swing
sizes are comparable** between the two (Bottom-Up's monthly bias ranges
-6,929 to +5,697; Top-Down's ranges -5,956 to +7,573). The difference is in
how well those swings cancel over the year: Bottom-Up's **net to -2.5%**,
Top-Down's **net to +7.1%** — a real, verified 2.8x difference, not noise.
The likely mechanism: Bottom-Up sums 6 *independently* fit local SBA/ADIDA
models, each initialized and updated on its own local demand history, so
their lag timing isn't perfectly synchronized — giving a mild diversification
benefit when summed. Top-Down's single aggregate-level SBA model has no such
diversity to average over; its lag is applied uniformly to the whole national
series with nothing to partially cancel it.

**This means Bottom-Up's national-level win here is not obviously the
textbook "Bottom-Up preserves location-specific signal" advantage** (Section
2.2 of the reconciliation context document) — both approaches are limited by
the *same* weak univariate method, not by fundamentally different
information content. The win looks more like an artifact of *how many
independently-lagged copies of the same weak method get summed* than
evidence Bottom-Up is "seeing" real location-level demand shifts Top-Down
misses. Worth stating plainly so this result isn't over-generalized to
future method changes — if either level moves to a seasonally-aware method,
this specific gap could shrink or disappear.

## Results — location level (n=6,054 product×location series)

| method | rmse_mean | rmse_median | bias_mean | % of series winning RMSE |
|---|---|---|---|---|
| Bottom-Up (native) | 0.5943 | 0.6048 | -0.0014 | 59.8% |
| Top-Down (disaggregated) | 0.5943 | 0.6052 | +0.0041 | 40.2% |

By demand-pattern category:

| category | n_series | BU rmse_mean | TD rmse_mean | BU bias_mean | TD bias_mean | % BU wins |
|---|---|---|---|---|---|---|
| intermittent | 5,862 | 0.5976 | 0.5976 | -0.0014 | +0.0041 | 60.1% |
| lumpy | 192 | 0.4935 | 0.4929 | -0.0019 | +0.0049 | 50.5% |

**At location level the two methods are essentially tied on RMSE** — pooled
means agree to four decimal places (0.5943 vs. 0.5943), and the win rate
(59.8%/40.2%) is far closer to a coin flip than the 80.4%/19.6% split seen
nationally. The Lumpy segment is a literal coin flip (50.5%). Bias direction
still differs (Bottom-Up slightly over-forecasts, Top-Down slightly
under-forecasts) but both magnitudes are small (0.0014 vs. 0.0041).

## Does the winner differ between levels?

**No — Bottom-Up wins (or ties) at both levels, it doesn't flip.** The
reconciliation context document's Section 2.1 flags the *possibility* that
"Top-Down could win nationally but lose at location level" given its known
blindness to location shifts; that pattern is **not** what happened here.
Instead, Bottom-Up's advantage is largest exactly where Top-Down should be
strongest (national, decisively — 80.4%/19.6%) and narrows to a near-tie at
the level Bottom-Up is supposed to be strongest (location, 59.8%/40.2%) —
the opposite direction of narrowing from what the textbook trade-off would
predict, reinforcing the read above that this comparison is currently being
driven by the shared SBA seasonal-lag weakness rather than by the two
methods' textbook information trade-offs.

## Recommendation

- **Bottom-Up is the better candidate to carry forward** from this
  comparison — it wins clearly at national grain and at worst ties at
  location grain, with no scenario in this backtest where Top-Down is
  the clear winner.
- If Stage 4 finds MinT infeasible, **Bottom-Up is the fallback
  recommendation**, not Top-Down, per the plan's own instruction to pick
  "the better of Top-Down/Bottom-Up from Stage 3."
- Flag for whoever picks this up next: the national-level gap between the
  two methods is substantially explained by SBA's seasonal-lag bias
  (documented in `stage2`'s report and reconfirmed here), which is a
  property of the *underlying univariate method*, not of Top-Down vs.
  Bottom-Up as reconciliation strategies per se. A seasonally-aware base
  method (e.g., a seasonal variant of exponential smoothing, or explicitly
  modeling the Jan-Apr/Oct-Dec vs. May-Sep cycle) is a more promising lever
  for improving *either* approach than switching between them.

## Hand-off

The "shared-weakness, not information trade-off" reading of why Bottom-Up wins here carries
into the MinT feasibility check (`../stage4_mint_feasibility/`).
