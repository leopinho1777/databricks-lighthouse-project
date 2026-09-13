# Demand Forecasting Workstream — Overview

This is the consolidated narrative for everything under `forecasting/`: what
was done, what was tested against live data, what was validated with real
numbers, and where each detailed write-up lives. `README.md` in this
directory is the terse "what to run" reference; this document is the "what
happened and why" one.

## Scope and constraints

Exploratory workstream for the demand-forecasting Action Plan's Task 1.1
(forecasting unit/granularity), 1.2 (forecast horizon), and 1.5
(train/val/test split), later extended into a segmented-treatment phase
(classify by demand pattern, apply intermittent-demand methods) and a
hierarchical-reconciliation phase (product-level vs. product×location
forecasting, and how to make the two coherent). Everything here is
**exploratory and prototype-only**:

- No ML/regression model is built anywhere in this workstream — only
  statistical baselines (Seasonal Naive, Moving Average, SES) and classical
  intermittent-demand methods (Croston, SBA, ADIDA).
- `fact_demand_daily` (`develop.eros_analytics_forecasting_scratch.fact_demand_daily`)
  is a disposable scratch table, not a committed dbt model — rebuildable at
  will, not something downstream jobs depend on.
- All scripts connect to the live Databricks dev warehouse via the existing
  `~/.dbt/profiles.yml` dev profile; nothing secret is stored in this repo.
- Large per-row query results are cached as gitignored `output/_*.parquet`
  files; only small summary CSVs that back the markdown reports are tracked
  in git.

## The narrative arc

Each stage's finding motivated the next — this is the throughline connecting
seven stages that might otherwise read as independent exercises:

1. **01** grounded the forecasting unit in real data and surfaced that
   warehouses sell almost as much as stores do — an open question for the
   team, not resolved here.
2. **02** designed `fact_demand_daily`, the one fact table every later stage
   builds on, and flagged that its zero-fill spine starts from one global
   date rather than each product's real launch date.
3. **03** backtested three standard baselines at daily/weekly/monthly grain
   and found per-series and portfolio-level rankings actively disagree —
   plus a structural growth-trend bias in Seasonal Naive that recurs as a
   theme through every later stage.
4. **04** explained *why* daily grain looked so sparse in `03`: the catalog
   is 96.8% Intermittent / 3.2% Lumpy by the standard ADI/CV² classification,
   with **zero** Smooth or Erratic series — the sparsity is structural, not
   a modeling failure.
5. **05** applied the textbook prescription for that finding — Croston/SBA —
   and validated it against `03`'s baselines with real backtest numbers,
   including a documented case where the standard accuracy metrics
   (sMAPE/MAPE) become structurally uninformative for this catalog.
6. **06** tested the two follow-up questions `04` raised (does aggregating
   over time fix the sparsity; does ADIDA improve on `05`) and answered both
   empirically: no, and no (not meaningfully).
7. **07** picked up a different aggregation axis — location, not time — to
   ask whether *national* product-level demand behaves better, then ran a
   full Top-Down/Bottom-Up/MinT reconciliation comparison to decide how to
   combine that national signal with the location-level detail the business
   actually needs.

## Stage-by-stage summary

### 01 — Data exploration ([`01_data_exploration_summary.md`](01_data_exploration/01_data_exploration_summary.md))

**Tested:** table inventory and grain of every relevant mart (`fct_sales`,
`dim_products`, `dim_locations`, `dim_calendary`, `fct_daily_stock_levels`,
`fct_returns`); a location-type split; a 2020-2021 anomaly check; a
censored-demand check.

**Validated:**
- Marts are clean at this layer — 0% nulls on key columns, 0 duplicates, 0
  future-dated rows in `fct_sales`.
- Exactly 6 locations, cleanly typed 3 stores / 3 warehouses — but
  **warehouses generate almost exactly as much direct sales volume as
  stores** (378K vs. 377K units), contradicting the usual
  warehouse-replenishes-store mental model. Still an open question for the
  team on what "product × store" should even mean for Task 1.1.
- **No 2020-2021 COVID-era anomaly** — this is mock data with a smooth
  ~14-17% YoY growth trend, not a real-world disruption. No correction logic
  needed.
- A stock-levels future-dating bug (77% of rows dated into 2027) was found,
  fixed upstream, and reverified at 0% post-fix. The *separate*, unrelated
  problem — stock history is too sparse (~1.2 snapshots per product×location
  pair) to support a confident censored-demand read — remains open; it was
  never a future-dating issue and the fix didn't touch it.

### 02 — Schema design ([`02_ideal_schema_proposal.md`](02_schema_design/02_ideal_schema_proposal.md))

**Built:** `fact_demand_daily` — one row per (date, product_variant_id,
location_id), dense/zero-filled, 14.8M rows, in a disposable scratch schema.

**Validated:** reconciles exactly against `fct_sales`
(`sum(qty_sold_gross)` matches to the row, 649,523 = 649,523). Every
weekly/monthly rollup used from `03` onward is a `group by` over this table,
never reprocessing raw source data again.

**Documented, not resolved:**
- The zero-fill spine starts from one *global* date lower bound, not each
  product's real launch date — flagged and revisited operationally in `04`
  and `05` via left-trimming to each series' own first sale, but the
  underlying table itself was never rebuilt with a per-pair bound.
- No store-to-serving-DC transfer data exists in the source system at all —
  blocks any future "assess new DC need" analysis.
- Gross vs. net demand as the target, and the stock-history sparsity from
  `01`, are both deferred rather than solved.

### 03 — Granularity & baselines ([`03_granularity_comparison_report.md`](03_granularity_baselines/03_granularity_comparison_report.md))

**Tested:** Seasonal Naive, Moving Average (28d/4wk/3mo), and SES (α=0.3)
against the full 6,054-series catalog at daily, weekly, and monthly grain,
2020-2024 train / 2025 holdout.

**Validated:**
- **Per-series and portfolio-level rankings disagree.** Seasonal Naive wins
  decisively per-series at every grain (it trivially gets zero-actual days
  right); SES/Moving Average win at the portfolio level for daily/weekly
  (aggregate totals are noisy but not sparse).
- **Seasonal Naive has a structural, growth-driven positive bias** that
  grows with the aggregation window (portfolio bias +52 daily → +1,563
  monthly) — a recurring theme flagged again independently in Stage 2 of
  `07` for SBA.
- Daily grain's 73.1% zero-actual rate (full 2020-2025 history) is an
  intermittent-demand artifact, not a data quality problem — this is the
  observation `04` goes on to formalize.

**Recommendation:** weekly grain as the Task 1.1 default (later work in `05`/`06` operated at daily grain instead, to directly address the intermittent-demand finding this stage surfaced).

### 04 — Demand pattern classification ([`04_demand_classification_summary.md`](04_demand_classification/04_demand_classification_summary.md))

**Tested:** ADI/CV² classification (Syntetos-Boylan-Croston framework, full
6,054-series catalog, no sampling) at daily grain.

**Validated:** **96.8% Intermittent, 3.2% Lumpy, 0% Smooth, 0% Erratic.**
The lowest ADI in the entire catalog is ~45x the classification threshold —
the standard 1.32-day threshold (calibrated for weekly/monthly industrial
spare-parts review cycles) doesn't discriminate at all at daily retail grain
for this catalog; the split is driven entirely by CV². This is presented
explicitly as a real, structural finding, not a broken classification.

**Documented, routed forward:** the entire catalog is in scope for
Croston/SBA (Strategy 2) since there's no Smooth segment to exclude —
directly sets up `05`.

### 05 — Croston/SBA backtest ([`05_croston_sba_summary.md`](05_croston_sba/05_croston_sba_summary.md))

**Tested:** classic Croston's method and its SBA bias correction (α=0.1),
full catalog, same 2025 holdout, benchmarked against `03`'s three baselines.

**Validated:**
- **Croston/SBA wins on per-series RMSE** (0.594-0.595) over all three `03`
  baselines (0.603-0.835) — but **loses at the portfolio-total level**
  (175-177 vs. 101-107 for SES/Moving Average) — the same
  per-series-vs-portfolio tension `03` first surfaced, now reproduced with a
  purpose-built intermittent-demand method.
- **sMAPE/MAPE are structurally uninformative for this method on this
  catalog** — they saturate near their analytic maximum (2.0) whenever
  actual=0 and forecast>0, which describes ~73% of rows, since Croston-family
  forecasts almost never land on exact zero. RMSE/Bias are established here
  as the trustworthy metrics for every subsequent stage.
- **SBA strictly improves on raw Croston** — bias magnitude more than halves
  both per-series and at portfolio level, with no RMSE cost. SBA, not raw
  Croston, is carried forward everywhere downstream.

### 06 — Multi-grain / ADIDA ([`06_multi_grain_summary.md`](06_multi_grain/06_multi_grain_summary.md))

**Tested:** (a) ADI/CV² reclassification at weekly grain; (b) ADIDA — SBA
fit at weekly grain, disaggregated to daily via a uniform 1/7 split —
benchmarked against `05`'s native daily SBA.

**Validated:**
- **Aggregating over time does not create a Smooth/Erratic segment** — the
  lowest weekly ADI is still 6.5x the threshold. The one real shift is CV²:
  the Lumpy share roughly doubles (3.2%→6.3%) as weekly-bucketed sale sizes
  become more variable — confirms `04`'s finding rather than complicating it.
- **ADIDA gives no meaningful lift over native daily SBA**: pooled RMSE
  differs by 0.02%, the win rate is a near-coin-flip (54.4%), and 97.7% of
  series land within ±1% of each other. A modest, consistent bias
  improvement is the only real effect.
- **Recommendation, and the artifact every later stage depends on**:
  default to `05`'s native daily SBA catalog-wide; the small per-series
  ADIDA carve-out (~1% of series with a genuine >2% improvement) is
  persisted in `output/_recommended_forecasts.parquet` — this file is the
  committed per-series/per-day forecast that unblocks `07`.

### 07 — Hierarchical reconciliation ([`07_hierarchical_reconciliation_summary.md`](07_hierarchical_reconciliation/07_hierarchical_reconciliation_summary.md))

Tests whether *location*-aggregation (rather than `06`'s time-aggregation)
changes the demand-pattern picture, then runs a full Top-Down / Bottom-Up /
MinT reconciliation comparison. Gated behind `05`/`06` existing with real
committed output (a deliberate hard block, not an oversight — see the
context document at
[`.claude/context_hierarchical_reconciliation_plan.md`](../.claude/context_hierarchical_reconciliation_plan.md)).

- **Stage 1 — Bottom-Up** ([report](07_hierarchical_reconciliation/stage1_bottom_up/stage1_bottom_up_report.md)):
  sums `06`'s recommended per-series forecast across all 6 locations.
  National zero-actual sparsity drops from ~99% (per-location, 2025 holdout)
  to ~94% (national) — real, but far from Smooth. Per-product RMSE (1.553
  mean) scales close to what independent per-location errors would predict.
- **Stage 2 — Top-Down** ([report](07_hierarchical_reconciliation/stage2_top_down/stage2_top_down_report.md)):
  fits SBA directly on the national aggregate, disaggregates via static
  historical location shares. National reclassification finds the **Lumpy
  segment disappears entirely** (aggregating locations reduces sale-size
  variability via a real central-limit effect) — but ADI still doesn't
  move, so the whole catalog still routes to SBA. A deep-dive into SBA's
  national bias found it's driven by a **strong seasonal cycle** (high
  Jan-Apr/Oct-Dec, low May-Sep) that SBA's slow-adapting α=0.1 smoothing
  can't track — a 7.1% net annual under-forecast, verified both at the
  portfolio level and across 69.2% of individual products.
- **Stage 3 — Comparison** ([report](07_hierarchical_reconciliation/stage3_comparison/stage3_comparison_report.md)):
  **Bottom-Up wins decisively at national level** (80.4% of products,
  portfolio RMSE 3.7% lower, bias magnitude 2.9x smaller) and **ties at
  location level** (59.8%/40.2%, pooled RMSE identical to 4 decimals) — the
  opposite of the "Top-Down wins nationally, loses locally" pattern the
  literature would predict. Traced to both methods sharing the same SBA
  seasonal-lag weakness; Bottom-Up's win looks like a diversification effect
  from summing 6 independently-lagged local models, not clear evidence of
  genuine location-specific signal Top-Down structurally can't see.
- **Stage 4 — MinT feasibility** ([report](07_hierarchical_reconciliation/stage4_mint_feasibility/output/mint_feasibility_check.md)):
  **not feasible at either level.** Holdout periods are 12.1% (national) and
  2.0% (location) of the rule-of-thumb minimum; the resulting
  error-covariance matrices are **exactly singular** (94.0% of
  location-level eigen-directions are exactly zero), not just
  ill-conditioned. A shrinkage/diagonal MinT variant is flagged as a more
  realistic future path than waiting for more data (which would need
  ~49-82 more years at location grain — not realistic ever).
- **Final recommendation:** carry **Bottom-Up** forward — it wins or ties at
  both hierarchy levels and needs no covariance estimation, unlike MinT.

## Cross-cutting methodology (applies across `03`-`07`)

- **Same holdout every time:** 2020-2024 train / 2025 holdout, determined
  dynamically (`most_recent_complete_year()`), reused verbatim from `03`
  in every later stage rather than re-derived — so every stage's numbers are
  directly comparable to each other.
- **Same metrics every time:** RMSE, Bias, MAPE (zero-actual excluded), and
  sMAPE, via `03`'s `compute_metrics()`, reused verbatim throughout. `05`
  established that sMAPE/MAPE become structurally uninformative for
  Croston-family methods on this catalog (they saturate near their analytic
  maximum on the catalog's dominant zero-actual days) — every later stage
  (`06`, `07`) explicitly carries this caveat forward and reports RMSE/Bias
  as the metrics to trust.
- **No lookahead, enforced consistently:** `.shift(1)` after rolling/`ewm()`
  calculations for the baselines; the equivalent sequential state-update
  discipline for Croston/SBA (state only updates using data through `t-1`
  before producing period `t`'s forecast).
- **Left-trimming, applied consistently:** every per-series calculation
  (ADI/CV², Croston/SBA state) starts from each series' own first non-zero
  observation, not the table's global zero-fill start — because `02`'s
  schema builds the spine from one global date bound rather than each
  product's real launch date.
- **Reuse-in-place, not reimplementation:** `04` reused `03`'s cached daily
  parquet directly; `05` reused `03`'s `most_recent_complete_year`/
  `compute_metrics`; `06` reused `04`'s classification functions and `05`'s
  `croston_sba()`; `07` reused all of the above plus `06`'s recommended
  forecast cache. No forecasting logic was rewritten at any stage — this is
  a deliberate project convention, not an oversight of code duplication.
- **Checkpoint discipline:** every stage stops and reports before the next
  one starts, matching the plan's own explicit review requirement — visible
  in every stage report's closing "Checkpoint" section.
- **Tracked vs. gitignored outputs:** every stage keeps large per-row query
  results and per-series/per-day forecast values in gitignored
  `output/_*.parquet` caches, and only small summary CSVs (the ones backing
  each markdown report's tables) in tracked `output/*.csv` files.

## What's validated vs. what's still open

**Validated with real, reproducible numbers:**
- The catalog is structurally intermittent (96.8%/3.2% Intermittent/Lumpy,
  0% Smooth/Erratic) at daily grain, and this doesn't change at weekly grain
  or at national (location-aggregated) grain either — only the
  Lumpy/Intermittent split shifts, for different reasons at each aggregation
  axis.
- SBA is the strongest per-series intermittent-demand method tested, ADIDA
  doesn't meaningfully improve on it, and Bottom-Up reconciliation beats
  Top-Down at both hierarchy levels with today's base methods.
- MinT is not viable with current data maturity, quantifiably so (not "might
  be risky" — the covariance matrices are exactly singular).

**Still open, explicitly not resolved by this workstream:**
- Whether warehouse-attributed sales should count toward "product × store"
  demand at all (`01`) — a business/data-semantics decision, not a modeling
  one.
- Stock-history sparsity (`01`), which keeps `is_stockout_day`/
  `is_demand_censored_flag` unreliable — unrelated to and unresolved by the
  future-dating fix that was applied.
- `fact_demand_daily`'s global (not per-product) zero-fill start date (`02`)
  — worked around via left-trimming in every downstream calculation, but the
  underlying table was never rebuilt.
- Seasonal Naive's (`03`) and SBA's (`07`) shared structural weakness:
  neither has an explicit trend or seasonality component, so both
  systematically mis-forecast around this catalog's ~15%/year growth trend
  and its Jan-Apr/Oct-Dec seasonal cycle. This is flagged as the most
  promising lever for a future phase — more so than switching between
  Top-Down/Bottom-Up/MinT.
- A shrinkage or diagonal-covariance MinT variant (`07`, Stage 4) — a
  smaller, different scope of work than the full-sample-covariance approach
  that was gated out, and not itself tested.

## Directory map

```
forecasting/
  README.md                              # quick-start: how to run every script, in order
  OVERVIEW.md                            # this file
  _shared/db_connection.py               # shared Databricks connection helper (dbt dev profile)
  01_data_exploration/                   # table inventory, location-type split, anomaly + censoring checks
  02_schema_design/                      # fact_demand_daily prototype (build script + SQL + proposal doc)
  03_granularity_baselines/              # Seasonal Naive / Moving Average / SES, daily/weekly/monthly
  04_demand_classification/              # ADI/CV² classification, full catalog, daily grain
  05_croston_sba/                        # Croston + SBA backtest vs. 03's baselines
  06_multi_grain/                        # weekly reclassification + ADIDA vs. 05; produces the
                                          # per-series recommended-forecast cache 07 depends on
  07_hierarchical_reconciliation/        # Bottom-Up / Top-Down / MinT-feasibility, 4 stages + final summary
    stage1_bottom_up/
    stage2_top_down/
    stage3_comparison/
    stage4_mint_feasibility/
```

Each numbered stage directory follows the same shape: one `# %%`
percent-format script, one markdown write-up, and an `output/` directory
with small tracked CSVs (backing the write-up's tables) plus gitignored
`_*.parquet` caches (raw query results and per-series/per-day forecast
values, regenerable by re-running the script).
