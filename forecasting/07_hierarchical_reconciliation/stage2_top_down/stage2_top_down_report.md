# Hierarchical Reconciliation — Stage 2: Top-Down

Aggregates raw daily actuals to national grain (per product, summed across
all 6 locations), re-runs the Step A ADI/CV² diagnostic *at that grain*
before choosing a method, fits the routed forecast, then disaggregates back
to product×location using each location's historical share of national
demand. Produced by
[`run_stage2_top_down.py`](run_stage2_top_down.py); national reclassification
in
[`output/national_classification.csv`](output/national_classification.csv) /
[`output/national_category_summary.csv`](output/national_category_summary.csv),
national metrics in
[`output/top_down_national_metrics.csv`](output/top_down_national_metrics.csv),
location shares in
[`output/location_shares.csv`](output/location_shares.csv), disaggregated
location-level metrics in
[`output/top_down_location_metrics.csv`](output/top_down_location_metrics.csv),
monthly seasonal bias breakdown in
[`output/seasonal_bias_breakdown.csv`](output/seasonal_bias_breakdown.csv).

## Method

- **National series:** raw daily actuals (`qty_sold_net`) grouped by
  (`product_variant_id`, `period`), summed across all 6 locations —
  1,009 series, one per product. Given a constant `location_id="NATIONAL"`
  tag so `03`'s `add_moving_average`/`add_ses` (which key off `03`'s own
  module-level `KEYS = ["product_variant_id", "location_id"]`) apply
  unmodified — no forecasting logic was rewritten for this stage.
- **Reclassification:** `04`'s `compute_series_stats`/`classify_category`
  reused verbatim, same 1.32/0.49 thresholds, applied to the national series
  (left-trimmed to each product's own first national sale).
- **Routing:** Moving Average (`03`'s daily window=28) for any
  Smooth/Erratic product, SBA (`05`'s α=0.1) otherwise. Both are computed
  for every product regardless of routing, for a full comparison table.
- **Location shares:** each location's share of national demand per product,
  computed over the **pre-holdout training window** — all years strictly
  before the holdout year (2020-2024), summed from that product's own first
  sale onward. Static per (product, location), applied uniformly across every
  2025 holdout day — the classic Top-Down assumption that relative shares
  are stable, made explicit and testable here rather than assumed.
- **Metrics:** `03`'s `most_recent_complete_year`/`compute_metrics` reused
  verbatim, same 2025 holdout year as every prior stage.

## Results — national-grain reclassification

| category | n_series | % of series | % of volume |
|---|---|---|---|
| intermittent | 1,009 | 100.0% | 100.0% |
| smooth / erratic / lumpy | 0 | 0.0% | 0.0% |

**No Smooth or Erratic segment emerges — but the Lumpy segment vanishes too**,
unlike the location-grain (3.2% Lumpy) or weekly-location-grain (6.3% Lumpy)
classifications. This is a genuinely new and interesting result, not just
"aggregation doesn't help, again": summing 6 quasi-independent locations'
demand *does* reduce sale-size variability (CV²) — several products that
were Lumpy at location grain drop below the 0.49 CV² threshold once
aggregated nationally, a real central-limit-style effect. **What doesn't
move is ADI.** National zero-actual sparsity is still ~94% in the 2025
holdout (Stage 1's finding), giving every product an ADI far above the 1.32
threshold regardless of the CV² improvement — so the routed method is SBA
for all 1,009 products (`top_down_routed` metrics below are identical,
row-for-row, to the `sba` row, confirming the routing logic is doing exactly
what the classification says it should).

## Results — national metrics, per method (n=1,009 products)

| method | rmse_mean | rmse_median | bias_mean | smape_median |
|---|---|---|---|---|
| **top_down_routed (=sba)** | 1.555 | 1.550 | +0.0248 | 1.982 |
| moving_average | 1.574 | 1.573 | +0.0015 | 1.579 |
| ses | 1.677 | 1.674 | +0.0007 | 1.984 |

`top_down_routed` (SBA) has the best RMSE of the three, but Moving Average
has a **notably smaller bias magnitude** (+0.0015 vs. +0.0248, ~16x smaller)
for only a 1.2% RMSE cost, and a meaningfully lower sMAPE (1.579 vs. 1.982 —
still high, but the only method here that isn't fully saturated near the
metric's ceiling). The classification correctly routes to SBA per the stated
rule (no Smooth/Erratic segment to justify Moving Average), but this
bias/RMSE trade-off is worth carrying into any future revisit of the routing
rule itself — not acted on here, since the routing decision was fixed before
running the backtest.

### Why the bias gap: SBA can't keep up with the national demand's seasonal cycle

National 2025 actual demand is strongly seasonal — high in Jan-Apr and
Oct-Dec (11,300-16,800 units/month), low in May-Sep (4,900-7,200/month), a
roughly 3x swing. Monthly whole-portfolio totals
(`output/seasonal_bias_breakdown.csv`):

| month | actual | MA pred | SBA pred | bias (MA) | bias (SBA) |
|---|---|---|---|---|---|
| Jan | 16,820 | 15,242 | 9,247 | +1,578 | **+7,573** |
| Feb | 13,909 | 14,928 | 9,395 | -1,019 | +4,514 |
| Mar | 14,881 | 15,059 | 11,214 | -178 | +3,667 |
| Apr | 11,330 | 12,639 | 11,308 | -1,309 | +22 |
| May | 6,880 | 9,393 | 11,564 | -2,513 | -4,684 |
| Jun | 4,939 | 5,636 | 10,647 | -697 | -5,708 |
| Jul | 4,356 | 4,709 | 10,312 | -353 | **-5,956** |
| Aug | 5,915 | 5,224 | 9,450 | +691 | -3,535 |
| Sep | 7,171 | 6,548 | 8,456 | +623 | -1,285 |
| Oct | 11,311 | 9,782 | 8,540 | +1,529 | +2,771 |
| Nov | 14,877 | 12,714 | 8,715 | +2,163 | **+6,162** |
| Dec | 15,572 | 15,540 | 9,965 | +32 | +5,607 |
| **Total** | **127,961** | **127,412** | **118,813** | **+549 (0.4%)** | **+9,148 (7.1%)** |

SBA's α=0.1 updates its smoothed level by only 10% toward each new
observation — and only on days a sale actually occurs — so it reacts to a
seasonal turning point far more slowly than the 28-day rolling Moving
Average, which recomputes off the literal last 28 days every day regardless
of how sparse they are. The result: SBA **badly under-forecasts every high
season** (Jan +7,573, Nov +6,162, Dec +5,607 — still catching up from the
prior low) and **over-forecasts every low season** (Jul -5,956, Jun -5,708 —
still coasting down from the prior peak). Moving Average lags too (its
bias swings from -2,513 to +2,163 across the year) but the swings are
smaller and, crucially, largely cancel over the full year (net annual bias
just 0.4% of total volume) — while SBA's over- and under-forecast months
don't cancel, leaving a **7.1% net annual under-forecast**.

This is not a portfolio-level artifact — it's broad across the catalog:
**69.2% of the 1,009 products show a positive (under-forecast) bias under
SBA, vs. 52.3% under Moving Average** (near coin-flip, as expected from a
well-centered method). Median absolute bias per product is 0.045 for SBA
vs. 0.013 for Moving Average — a ~3.5x gap, consistent with a systematic
skew rather than noise.

SBA still wins on pooled RMSE despite this, because RMSE penalizes squared
error variance, not systematic drift: SBA's very smooth, slow-moving
forecast avoids overshooting on individual sparse demand spikes the way a
28-day window can (a single spike keeps inflating the moving average for
the following 4 weeks), so its day-to-day error variance is lower even
though its seasonal-lag bias is worse. RMSE and Bias are measuring two
different failure modes here, and neither alone tells the full story.

## Results — location shares (n=6,054 product×location pairs)

Shares sum to exactly 1.0 per product (mean 1.0000000, by construction) with
real spread: mean share 16.7% (≈1/6, as expected with 6 locations), but
ranging from 1.9% to 39.0% — locations are not interchangeable for a given
product, confirming genuine location-level demand heterogeneity rather than
a uniform 1-in-6 split. Every product×location pair had at least one sale in
the 2020-2024 training window (0 zero-share pairs, 0 undefined shares) — the
edge case of a product/location combination with no training-window history
never arose, so no fallback rule was needed for it in this run.

## Results — disaggregated location-level metrics (n=6,054 series)

| rmse_mean | rmse_median | bias_mean | series fully excluded |
|---|---|---|---|
| 0.5943 | 0.6052 | +0.0041 | 0 / 6,054 |

**Nearly identical in RMSE to `05`/`06`'s native per-location numbers**
(0.594-0.605 mean/median there too), despite being built from a completely
different process (one national model, split by a static historical share)
rather than 6,054 independently-fit local models. At this per-series scale,
where the typical product×location day sells 0-2 units, RMSE appears to be
largely floor-set by the data's own low-count variance rather than by which
of these two reasonable methods produced the forecast — a caveat worth
carrying into Stage 3 rather than over-reading small RMSE deltas there.
**Bias direction differs, though**: Top-Down's disaggregated bias is
positive (+0.0041, slight under-forecast) where `05`/`06`'s native Bottom-Up
bias was negative (-0.0012 to -0.0019, slight over-forecast) — opposite
signs. Full side-by-side belongs in Stage 3, not here, but it's visible
already in these two stages' numbers independently.

## Checkpoint

Stopping here per the project's step-by-step review requirement (same
convention as every prior stage). Stage 3 (direct Bottom-Up vs. Top-Down
comparison, national and location level) is designed in the plan but not yet
implemented — pending review of the findings above, in particular the
CV²-improves-but-ADI-doesn't national reclassification result and the
location-level RMSE-floor caveat.
