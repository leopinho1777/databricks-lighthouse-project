# Decision-Horizon Evaluation and Product-Axis Aggregation — Stage 08

Three tests layered on `04`-`07`, each answering a question those stages left
open or framed differently: does the ADI/CV² picture change at the client's
actual decision grain (monthly) and along the product axis; does the method
ranking change when error is measured over the decision horizon (15/30 days)
instead of per day; and does aggregating by product and disaggregating back
beat forecasting each SKU directly. Produced by
[`run_decision_horizon.py`](run_decision_horizon.py); raw numbers in
[`output/`](output/).

## Scope and relationship to earlier stages

- `04` classified at daily grain and `06` at weekly grain; both found 0% Smooth.
  This stage adds **monthly grain** (the client's purchasing cycle) and the
  **product axis** (category and `product_id`), neither of which was covered.
- `07` aggregated across **locations** (6 series per product). This stage
  aggregates across **products** (~92 SKUs per category, 2 variants per
  product), and evaluates at the decision horizon rather than per day.
- Methods are limited to **Moving Average (28d)** — the mandated baseline — and
  **Seasonal Naive**. Croston/SBA is deliberately excluded: it needs sequential
  state updates, which cannot be expressed in SQL, and a second implementation
  would not be comparable to `05`'s.

  ## Method

- **Source:** `fct_sales` in `develop.eva_analytics_marts`, filtered to
  `order_status IN ('paid','confirmed')` and densified against `dim_calendary`.
  Unlike `03`-`07`, this stage does not read `02`'s `fact_demand_daily`
  prototype, so it has no dependency on another developer's scratch schema —
  the trade-off is **gross** quantity here versus **net** there. The calibration
  checks below quantify the difference at ~0.2%.
- **Execution:** every aggregation is pushed down to the SQL warehouse through
  `_shared/db_connection.py`; only summary rows are returned and reduced in
  pandas. There are no temporary views, because `query_df` opens one connection
  per call — each query is self-contained via CTEs.
- **Holdout:** 2025, the same year used in `03`-`07`, so numbers stay comparable
  across stages.
- **No lookahead:** the moving average uses
  `ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING`, so day *t* never sees its own
  value. Seasonal Naive joins on `ADD_MONTHS(dia, -12)` rather than an integer
  offset, for the same leap-year reason `03` documents.
- **Classification:** same ADI/CV² definitions and 1.32/0.49 thresholds as `04`,
  including the left-trim to each series' own first non-zero period.
- **Window evaluation:** non-overlapping buckets of 15 and 30 days within the
  holdout; actuals and forecasts are summed inside each bucket before the error
  is computed. The final incomplete bucket of the year is dropped.
- **Metrics:** RMSE and Bias as in `03`-`07`, plus **WAPE** (total absolute
  error ÷ total demand). WAPE is added because it is the only metric here that
  is comparable **across levels** — a category series is ~92x larger than a SKU
  series, so RMSE cannot be compared between them — and because it stays defined
  with zero actuals, unlike MAPE (see `05`'s metric-artifact finding).
- **Disaggregation shares:** each SKU's historical share of its parent, computed
  on **2020-2024 only**. Using holdout data to build the shares would leak the
  answer into the test.

## Results

### 1. Demand-pattern classification by grain and level

| level | grain | Smooth | Erratic | Intermittent | Lumpy |
|---|---|---|---|---|---|
| SKU × location | daily | 0.0% | 0.0% | 97.0% | 3.0% |
| SKU × location | weekly | 0.0% | 0.0% | 93.9% | 6.1% |
| SKU × location | monthly | 0.0% | 0.0% | 82.5% | 17.5% |
| Category × location | weekly | **51.5%** | 39.4% | 3.0% | 6.1% |
| Category × location | monthly | **92.4%** | 7.6% | 0.0% | 0.0% |

Median ADI at SKU × location is 117.8 (daily), 17.3 (weekly) and 4.4 (monthly)
— still 3.3x the 1.32 threshold even at the client's decision grain. At
category × location it is 1.1 (weekly) and 1.0 (monthly).

### 2. Error measured over the decision horizon

| level | window | method | RMSE/series | bias/series | WAPE | portfolio RMSE |
|---|---|---|---|---|---|---|
| SKU × location | 1 day | moving average | 0.606 | 0.000 | 197.2% | 107.3 |
| SKU × location | 1 day | seasonal naive | 0.839 | 0.009 | 183.6% | 135.7 |
| SKU × location | 15 days | moving average | **2.191** | 0.005 | **129.6%** | 799.3 |
| SKU × location | 15 days | seasonal naive | 3.202 | 0.130 | 165.1% | 961.9 |
| SKU × location | 30 days | moving average | **2.452** | 0.009 | **81.1%** | 1,346.8 |
| SKU × location | 30 days | seasonal naive | 4.498 | 0.260 | 149.5% | 1,826.6 |
| Category × location | 15 days | moving average | 26.80 | 0.435 | **26.3%** | 799.3 |
| Category × location | 15 days | seasonal naive | 36.30 | 11.92 | 35.7% | 961.9 |
| Category × location | 30 days | moving average | 35.47 | 0.87 | **17.7%** | 1,346.8 |
| Category × location | 30 days | seasonal naive | 53.82 | 23.84 | 27.0% | 1,826.6 |

### 3. Aggregate-then-disaggregate vs. forecasting each SKU directly

All three paths evaluated **at SKU × location**, moving average only.

| window | path | series aggregated | RMSE/series | WAPE |
|---|---|---|---|---|
| 15 days | A — direct per SKU | 1 | **2.191** | **129.6%** |
| 15 days | C — via `product_id` | 2 | 2.299 | 148.4% |
| 15 days | B — via category | ~92 | 2.331 | 166.4% |
| 30 days | A — direct per SKU | 1 | **2.452** | **81.1%** |
| 30 days | C — via `product_id` | 2 | 2.996 | 113.0% |
| 30 days | B — via category | ~92 | 3.317 | 142.2% |

### 4. Calibration and consistency checks

- **Against `04`:** daily classification here gives 5,870 Intermittent / 184
  Lumpy with median ADI 117.8, against `04`'s 5,862 / 192 and 118.9 — the
  gross-vs-net difference described in Method.
- **Against `06`:** the Lumpy share doubles from daily to weekly (3.0%→6.1%
  here, 3.2%→6.3% in `06`).
- **Against `05`:** daily per-series RMSE is 0.606 for Moving Average and 0.839
  for Seasonal Naive, against `05`'s 0.603 and 0.835.
- **Internal:** portfolio RMSE is identical across all three disaggregation
  paths and across both levels in §2 (107.3 / 799.3 / 1,346.8), as the linearity
  of a moving average requires — the paths distribute the same national total
  differently.
- **Coverage:** of the 5,925 series with demand in the holdout, 0 lacked
  pre-holdout history, so no SKU was structurally forced to a zero forecast in
  paths B and C.

## Discussion

**Time aggregation never produces a Smooth segment; product aggregation does.**
This closes the open question `04` raised about whether the ADI threshold needs
local recalibration: at SKU grain the catalog is genuinely non-smooth, and
coarsening the period from daily to monthly does not change that (median ADI
4.4, still 3.3x the threshold). Aggregating across ~92 SKUs does — 92.4% of
category × location series are Smooth at monthly grain. This matters because
the mandated moving-average baseline currently has **no segment it can be
applied to** under `04`'s result; at category level it does.

**At SKU level the error exceeds the demand it is predicting.** 129.6% WAPE
over 15 days and 81.1% over 30 days means the absolute error accumulated in a
window is of the same order as everything sold in it. The same method at
category level gives 26.3% and 17.7%. The practical reading is that reliable
numbers exist at the aggregate level and not at the item level, regardless of
method.

**Seasonal Naive's bias grows with the evaluation window** — from 0.009 per
series per day to 0.260 per 30-day window, and from 0.79 to 23.84 at category
level. This is `03`'s structural growth-trend bias, now measured in the window
where it turns into stockouts rather than into a daily accounting error.

**The disaggregation penalty is monotonic in how much you aggregate, and it is
already large at the smallest possible step.** Aggregating just two variants of
the same product costs 32 WAPE points over 30 days (81.1%→113.0%). The category
total is predictable; its composition is not, and that unpredictability is
present from the first level of aggregation. No intermediate level rescues the
top-down path for this catalog.

**This converges with `07`'s conclusion from an independent direction.** `07`
compared Bottom-Up and Top-Down along the **location** axis with a per-day
evaluation and found Bottom-Up wins. This stage compares them along the
**product** axis with a decision-horizon evaluation and finds the same. Two
different aggregation axes and two different evaluation horizons agreeing makes
the result look like a property of the catalog rather than of one test design.

## Recommendation

- **Keep Bottom-Up (direct per-SKU forecasting) for the SKU-level deliverable**,
  consistent with `07`'s recommendation, now supported on a second axis.
- **Report accuracy at the decision horizon, not per day**, and add WAPE
  alongside RMSE/Bias — it is the only metric here comparable across hierarchy
  levels and it stays defined with zero actuals.
- **Set expectations about SKU-level precision with the client.** The best path
  tested still misses ~81% of volume per SKU over 30 days, against ~18% at
  category level.

## What this stage does not test

- **No Croston/SBA**, for the reason given in Scope. `05` found SBA's daily
  per-series RMSE (0.594) close to Moving Average's (0.603), so a large reversal
  is not expected — but that is an expectation, not a measurement.
- **Static disaggregation shares.** Athanasopoulos, Ahmed & Hyndman (2009) show
  forecasted proportions outperform historical ones; this stage tested the
  weaker variant, so the Top-Down paths here are a lower bound.
- **One holdout year**, as in `03`-`07`. Task 1.6's rolling-origin validation
  remains outstanding for every stage.