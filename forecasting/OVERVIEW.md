# Demand Forecasting Workstream — Overview

This is the consolidated narrative for everything under `forecasting/`: what
was done, what was tested against live data, what was validated with real
numbers, and where each detailed write-up lives. `README.md` in this
directory is the terse "what to run" reference; this document is the "what
happened and why" one.

## Scope and constraints

Demand-forecasting analysis for the Action Plan's Task 1.1
(forecasting unit/granularity), 1.2 (forecast horizon), and 1.5
(train/val/test split), extended into a segmented-treatment phase
(classify by demand pattern, apply intermittent-demand methods), a
hierarchical-reconciliation phase (product-level vs. product×location
forecasting, and how to make the two coherent), a feature-engineering stage
(which covariates carry signal), and a model-comparison stage (which model
family forecasts best). Everything here is **analysis code, not a deployed
pipeline**:

- Phase 1 (`01`–`09`) uses only statistical baselines (Seasonal Naive, Moving
  Average, SES) and classical intermittent-demand methods (Croston, SBA,
  ADIDA). Stage 2 (`10`) fits a fixed-effects panel regression as a measuring
  instrument for candidate features. Stage 3 (`experiments/`, `11`) fits and
  compares five model families (panel regression, Random Forest, XGBoost,
  Prophet, SARIMA). None of them is deployed.
- `fact_demand_daily` is a disposable scratch table, not a committed dbt
  model — rebuildable at will, not something downstream jobs depend on. It
  lives in each developer's own dev schema (`<catalog>.<dev_schema>_forecasting_scratch.fact_demand_daily`,
  via `_shared/db_connection.py`'s `get_scratch_schema()`), not a shared or
  hardcoded schema — see `README.md`'s "Data source convention".
- All scripts connect to the live Databricks warehouse via the existing
  `~/.dbt/profiles.yml` dev profile; nothing secret is stored in this repo.
  Stable reference data (marts/staging) is read from the shared prod catalog
  regardless of whose profile is connected, so numbers stay comparable across
  developers.
- Large per-row query results are cached as gitignored `output/_*.parquet`
  files; only small summary CSVs that back the markdown reports are tracked
  in git.

## The narrative arc

Each stage's finding motivates the next — this is the throughline connecting
eleven stages that might otherwise read as independent exercises:

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
8. **08** revisited two assumptions the earlier stages share — that daily grain
   is the right place to measure error, and that location is *the* aggregation
   axis — and found the demand-pattern picture only changes along the product
   axis, while aggregating and disaggregating back costs more accuracy per SKU
   than forecasting each series directly.
9. **09** defined the baseline every model is measured against: a forecast
   made once at a cutoff and held static for the 91-day horizon, scored over
   four rolling origins, where Seasonal Naive beats Moving Average.
10. **10** tested which covariates carry signal and froze the feature set:
    only calendar earns a place, on top of a mandatory trend control.
11. **Stage 3** fit five model families on that set and compared them with the
    champion: none beats it convincingly, and the reasons trace back to the
    demand pattern `04` classified and the seasonality `03` documented.

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
- The source emits future-dated stock snapshots (77% of raw rows, dated into
  2027); `filter_future_dated()` removes them in staging, so
  `fct_daily_stock_levels` is 0% future-dated. Independently of that, stock
  history is too sparse (~1.2 snapshots per product×location pair) to
  support a confident censored-demand read, and that limitation remains open.

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
MinT reconciliation comparison. It depends on `05`/`06` having real committed
output (the recommended per-series forecast cache that `06` produces), which is
a hard prerequisite.

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

### 08 — Decision horizon & product axis ([`08_decision_horizon_summary.md`](08_decision_horizon_and_product_axis/08_decision_horizon_summary.md))

**Tested:** ADI/CV² classification at monthly grain and at category x location;
RMSE/Bias/WAPE over 15- and 30-day windows instead of per day; and direct
per-SKU forecasting against disaggregating a category-level and a
`product_id`-level forecast by historical shares. Moving Average and Seasonal
Naive only — Croston/SBA needs the sequential state that lives in `05`. Reads
`fct_sales` directly rather than `fact_demand_daily`, so gross instead of net
quantity; the stage's own calibration checks put that gap at ~0.2%.

**Validated:**
- **Time aggregation never creates a Smooth segment; product aggregation does.**
  0% Smooth at SKU x location at daily, weekly *and* monthly grain (median ADI
  117.8 / 17.3 / 4.4 — still 3.3x the 1.32 threshold at the client's own
  decision grain); 92.4% Smooth at category x location monthly. Closes `04`'s
  open question about whether the threshold needed local recalibration.
- **At SKU level the error exceeds the demand it predicts**: 129.6% WAPE over
  15 days and 81.1% over 30, against 26.3% and 17.7% at category level.
- **The disaggregation penalty grows with the degree of aggregation**, and is
  already 32 WAPE points at the smallest possible step (the two variants of one
  product): 81.1% -> 113.0% -> 142.2% over 30 days for the direct, `product_id`
  and category paths. No intermediate level rescues Top-Down for this catalog.
- **Independent convergence with `07`:** the same Bottom-Up verdict, reached on
  the product axis with a decision-horizon evaluation rather than the location
  axis with a per-day one.

**Documented, not resolved:** no Croston/SBA in the comparison; static rather
than forecasted disaggregation proportions, the weaker Top-Down variant
(Athanasopoulos, Ahmed & Hyndman, 2009); one holdout year, as everywhere else.

### 09 — Baseline close-out ([`09_baseline_close_out_summary.md`](09_baseline_close_out/09_baseline_close_out_summary.md))

**Defined:** the baseline for every later model — a Moving Average (28d) and a
Seasonal Naive forecast made once at each cutoff and held static for the ~91-day
horizon (tasks 1.2/1.3/1.4), scored over four rolling origins spanning 2025
(task 1.6) with a peak-season split (task 1.7) and logged to `/Shared/00_baseline`
(task 1.8).

**Validated:**
- **Seasonal Naive beats Moving Average at the 91-day horizon** in all four
  windows (WAPE 78.8–88.1% against 107.7–134.9%), the opposite of `03`'s
  1-week-horizon ranking: "same period last year" encodes the seasonal cycle a
  flat trailing average cannot anticipate. Seasonal Naive is the champion the
  Stage 3 models are compared against.
- **The forecast has to be held static.** A forecast recomputed as time passes
  sees real actuals from inside the window it is scored on; `08`'s 15/30-day
  WAPE is a re-bucketed one-step-ahead figure and is not comparable with the
  91-day numbers.

**Documented, not resolved:** bias is positive at every window (neither
baseline has a trend); only four origins; the baseline's WAPE counts only
series with sales in the window, a coverage difference from the Stage 3
scoring.

## Stage 2 — Feature Engineering ([`10_feature_engineering/`](10_feature_engineering/))

Separate from the granularity/baseline/classification workstream above:
tasks 2.1-2.10 of the project task tracker, building and testing a pooled
fixed-effects panel regression (product x location x ISO-week,
`PanelOLS(entity_effects=True)` + a linear time-trend structural control) as
a **measuring instrument** — its only job is isolating each candidate
feature group's individual effect, not competing as a Stage 3 model
candidate. Calendar, holidays, weather, economic, and marketing features
were each added as one cumulative layer and evaluated against a >2%
MAPE-improvement threshold; internal/inventory features were excluded
before or during testing (target leakage, data unavailability, and an
untestable-with-this-instrument stock-sparsity finding, respectively). An
independent COVID-anomaly check and a weather/calendar VIF check ran
alongside the cumulative chain. **Result: only calendar survives into the
production feature set** — via an accuracy-ablation test, not its own
threshold, since none of the five testable feature groups individually
cleared 2%. Full narrative: [`00_feature_backlog.md`](10_feature_engineering/00_feature_backlog.md)
(task-by-task, including the trend-control and scale-confound sensitivity
checks). Final output: [`10_frozen_feature_set.md`](10_feature_engineering/10_frozen_feature_set.md)
— the fixed input for every Stage 3 (task 3.n) session. Logged to the
`/Shared/01_feature_iteration` MLflow experiment.

## Stage 3 — Model comparison ([`experiments/`](experiments/README.md), [`11_model_comparison/`](11_model_comparison/11_model_comparison_report.md))

Five model families are fit and scored under one protocol (`experiments/_shared/evaluate.py`): total demand over
a 91-day window per (`product_variant_id`, `location_id`), the four rolling origins of `09` (2024-12-31,
2025-04-01, 2025-07-01, 2025-09-30), training only on data up to each cutoff, compared with the
`seasonal_naive_genuine_91d_v2` champion in `/Shared/00_baseline`. Each model may fit at whatever grain suits it;
only the scoring is shared. Everything is logged to `/Shared/02_model_comparison`, and each experiment has its own
`README.md` (design, how to run, results, limitations).

**The experiments** (portfolio WAPE at SKU × location; the champion scores 78.8 / 84.4 / 88.1 / 79.9 %):

- **Fixed-effects panel regression** ([`eva_regression/`](experiments/eva_regression/README.md), task 3.1): the
  Stage 2 specification refit per window. Uncorrected it under-forecasts total demand by ~71% (the log1p target
  yields a conditional median); with Duan's smearing it wins 2024-12-31 (78.1%) but over-corrects the low
  season (131.7% on 2025-07-01). Category × location WAPE reaches 11.4% in its best window.
- **Random Forest** ([`eros_randomforest/`](experiments/eros_randomforest/README.md), task 3.2): five
  configurations, 0 of 20 windows beaten. Depth is the dominant lever (`depth10` is best, 87.9–107.0%); a depth
  cap forces the forest to generalize across entities instead of memorizing them through raw ID codes.
- **XGBoost** ([`gabriel_xgboost/`](experiments/gabriel_xgboost/README.md), task 3.3): one global model on raw
  counts, tuned with Hyperopt on an earlier fold. The only model to beat the champion in a window (2024-12-31,
  77.1%), with the lowest per-series RMSE and bias, but 104.8% / 124.6% on the two low-season windows. It is fit
  once and applied at all four cutoffs, not refit per window, and 64.7% of its importance sits on `month`.
- **Prophet** ([`eros_prophet/`](experiments/eros_prophet/README.md), task 3.4): one model per series, five
  configurations, 0 of 20 beaten. Holidays add nothing (within 0.22 pp of the no-holiday run); a rigid trend is
  best on the two off-peak windows; multiplicative seasonality is unstable on a log1p target.
- **SARIMA** ([`pinho_sarima/`](experiments/pinho_sarima/README.md), task 3.5): a benchmark, 0 of 8 beaten.
  `d=0` with a trend term beats `d=1` on all four windows because first differencing over-differences a series
  that is already stationary around a trend.

**Final comparison** ([`11_model_comparison/`](11_model_comparison/11_model_comparison_report.md), task 3.7): every
committed configuration re-scored side by side from its `*_window_totals.csv`, no refit, logged as
`final_comparison_3_7`.

- **No trained model beats the champion convincingly.** None wins 3 of 4 windows; XGBoost and the panel
  regression with smearing each win one (by 1.8 pp and 0.8 pp, inside the noise of four windows).
- **Best of what was tested, not good:** the champion on portfolio WAPE (mean 82.8%); XGBoost v1 is the best
  trained model (lowest per-series RMSE and bias, level with the champion on the peak-season windows, category
  level 24.6%). At SKU × location every model sits at 77–132% WAPE; only category × location is usable (11–39%).
- **The data explains it:** 25–59% of series sell nothing in a 91-day window, a Poisson noise floor alone is
  27–45% WAPE, the annual cycle is already encoded by seasonal naive, and Stage 2 found no external signal. The
  log1p-target models forecast the median and under-forecast totals by 61–68%; only XGBoost (raw counts) and Duan
  smearing avoid that.
- **Open caveats:** the committed baseline WAPE counts only series with sales in the window while models are
  scored on all 6,054 series, so the ranking depends on how the two are aligned; weekly-grain models have shifted
  windows; XGBoost is not refit per window. The report states these rather than claiming the ranking is
  convention-proof.

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
- **Hand-offs:** most stage reports close with a hand-off or checkpoint section
  that states the verdict and what the next stage takes from it.
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
- At a genuine 91-day horizon Seasonal Naive is the strongest reference
  (79–88% WAPE at SKU × location), and none of the five Stage 3 model families
  beats it in more than one window (`experiments/`, `11`).
- Calendar is the only feature with measurable value and growth needs an
  explicit trend control; holidays, weather, economic indicators and marketing
  add about nothing (`10`), which a separate Prophet run without holidays
  reproduces.
- Forecasts become usable only when SKUs are aggregated: category × location
  reaches 11–39% WAPE for the two mean-targeting models, while SKU × location
  error is about the size of the demand (77–132%) for every model (`11`).

**Still open, explicitly not resolved by this workstream:**
- Whether warehouse-attributed sales should count toward "product × store"
  demand at all (`01`) — a business/data-semantics decision, not a modeling
  one.
- Stock-history sparsity (`01`), which keeps `is_stockout_day`/
  `is_demand_censored_flag` unreliable — independent of the future-date
  filtering in staging.
- `fact_demand_daily`'s global (not per-product) zero-fill start date (`02`)
  — worked around via left-trimming in every downstream calculation, but the
  underlying table was never rebuilt.
- Seasonal Naive (`03`) and SBA (`07`) have no explicit trend, so both
  under-forecast against this catalog's ~15%/year growth. The Stage 3 models
  with an explicit trend and season (panel regression, Random Forest, XGBoost,
  Prophet, SARIMA) did not beat Seasonal Naive, so the growth bias is real but
  not a sufficient explanation on its own. A trend-adjusted Seasonal Naive is
  the cheap reference that has not been tested.
- A shrinkage or diagonal-covariance MinT variant (`07`, Stage 4) — a
  smaller, different scope of work than the full-sample-covariance approach
  that was gated out, and not itself tested.
- The scoring-convention difference between the baseline (series with sales
  only) and the Stage 3 models (all series), which makes the champion ranking
  depend on how the two are aligned (`11`).
- XGBoost is fit once and not refit per window; a per-cutoff refit and a
  `month` ablation are untested (`experiments/gabriel_xgboost/README.md`).
- Croston/SBA and ADIDA (`05`/`06`) are not scored under the 91-day Stage 3
  protocol.

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
  08_decision_horizon_and_product_axis/  # monthly + product-axis classification, 15/30-day
                                         # window evaluation, disaggregation-path comparison
  09_baseline_close_out/                 # genuine 91-day held-static baseline, walk-forward,
                                         # peak-season split; logs /Shared/00_baseline in MLflow
  10_feature_engineering/                # Phase 2: pooled fixed-effects panel regression testing
                                         # calendar/holidays/weather/economic/marketing/inventory
                                         # cumulatively; see 00_feature_backlog.md and
                                         # 10_frozen_feature_set.md (fixed input for Stage 3)
  experiments/                           # Stage 3: shared protocol (_shared/evaluate.py) + one folder per model
                                         # (eva_regression, eros_randomforest, gabriel_xgboost, eros_prophet,
                                         # pinho_sarima), each with its own README.md
  11_model_comparison/                   # Stage 3 close-out (task 3.7): all experiments scored side by side
                                         # vs. the seasonal-naive champion; feeds the 3.8 champion decision
```

Each numbered stage directory follows the same shape: one `# %%`
percent-format script, one markdown write-up, and an `output/` directory
with small tracked CSVs (backing the write-up's tables) plus gitignored
`_*.parquet` caches (raw query results and per-series/per-day forecast
values, regenerable by re-running the script).
