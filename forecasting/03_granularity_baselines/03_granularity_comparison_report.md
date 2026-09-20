# Granularity Comparison Report — Demand Forecasting Phase 1

> **Data snapshot:** `fact_demand_daily` as built from the prod marts on 2026-09-11. These baselines are computed solely from `qty_sold_net` (sales-derived, reconciled exactly against `fct_sales` in Deliverable 2), so they do not depend on the stock-level columns; `is_stockout_day`/`is_demand_censored_flag` are not consumed anywhere in this backtest's math and are discussed in `01_data_exploration_summary.md` §4.

Full-catalog backtest (every product x location series in `fact_demand_daily`, no sampling — per team decision) of Seasonal Naive, Moving Average, and Simple Exponential Smoothing (SES) at daily, weekly, and monthly grain. Produced by [`run_baselines.py`](run_baselines.py); raw numbers in [`output/metrics_by_granularity_baseline.csv`](output/metrics_by_granularity_baseline.csv) (per-series, aggregated) and [`output/portfolio_total_metrics.csv`](output/portfolio_total_metrics.csv) (whole-portfolio total). **Baselines only — no regression/ML model was built or tuned.**

## Method

- **Split:** time-based, train on all years before the most recent complete calendar year, hold out that year. Determined dynamically from the data at each grain (a year counts as "complete" once its December is present) — resolved to **train 2020-2024, holdout 2025** for all three grains; the partial current year (2026) is excluded from both train and holdout.
- **No lookahead:** Moving Average and SES both apply `.shift(1)` after their rolling/`ewm()` calculation, so the forecast for period *t* only ever uses data through *t-1* (`rolling()`/`ewm()` include the current row by default, which would otherwise leak the actual value into its own forecast).
- **Seasonal Naive** is joined on the actual calendar date one year prior (`period - 1 year`), not an integer day-of-year — day-of-year misaligns by a day across the two leap years (2020, 2024) inside this range. Weekly grain snaps the shifted date to its ISO/Monday week start; monthly uses the month-start directly.
- **Windows:** Moving Average uses 28 days / 4 weeks / 3 months; SES uses a fixed `alpha=0.3` (closed-form `ewm()`, not a per-series fitted model — full-catalog scale made per-series `statsmodels` fitting unnecessarily slow for a baseline that isn't meant to be tuned).
- **Metrics:** RMSE and Bias (mean signed error, actual − forecast) computed normally. MAPE is undefined at zero actual demand — common at daily grain for a 1,009-SKU x 6-location catalog — so zero-actual rows are excluded from MAPE and the excluded % is reported; **sMAPE is reported alongside as the primary cross-granularity metric** since it stays defined in that case. Metrics are computed per series first, then summarized (mean/median) across the full catalog, plus a separate whole-portfolio run (all series summed per period) as a sanity upper bound.

## Results — per-series (median across all 6,054 product x location series)

| granularity | baseline | sMAPE (median) | MAPE (median) | RMSE (mean) | Bias (mean) | % rows excluded from MAPE (zero actual) |
|---|---|---|---|---|---|---|
| daily | seasonal_naive | **0.038** | 1.000 | 0.84 | +0.009 | 73.1% |
| daily | moving_average | 0.498 | 0.994 | 0.60 | +0.000 | 73.1% |
| daily | ses | 2.000 | 1.000 | 0.64 | +0.000 | 73.1% |
| weekly | seasonal_naive | **0.231** | 1.000 | 2.20 | +0.062 | — |
| weekly | moving_average | 0.577 | 0.970 | 1.75 | +0.003 | — |
| weekly | ses | 1.987 | 0.948 | 1.70 | +0.004 | — |
| monthly | seasonal_naive | **0.766** | 1.000 | 4.53 | +0.258 | — |
| monthly | moving_average | 1.250 | 0.835 | 3.80 | +0.055 | — |
| monthly | ses | 1.814 | 0.786 | 3.58 | +0.081 | — |

*(exact % excluded from MAPE per grain is in the CSV; daily is 73.1% — most individual SKU x location x day observations are legitimately zero, this is an intermittent-demand catalog, not a data quality issue).*

No series were fully excluded from Seasonal Naive for lack of a full year of history at any grain (0.0%) — because the `fact_demand_daily` prototype's spine is built from a *global* date lower bound (§ open question in `02_ideal_schema_proposal.md`), every series is dense back to 2020-01-01 regardless of when that product actually started selling, so this particular failure mode doesn't surface in this dataset. The check still runs and would report a nonzero % once the schema is rebuilt with a true per-product first-sale lower bound.

## Results — whole-portfolio total (sanity upper bound, all series summed per period)

| granularity | baseline | sMAPE | MAPE | RMSE | Bias |
|---|---|---|---|---|---|
| daily | seasonal_naive | 0.367 | 0.350 | 135 | +52 |
| daily | moving_average | 0.270 | 0.313 | 107 | +2 |
| daily | **ses** | **0.253** | **0.287** | 101 | +1 |
| weekly | seasonal_naive | 0.206 | 0.180 | 567 | +374 |
| weekly | **moving_average** | **0.171** | **0.178** | 496 | +19 |
| weekly | ses | 0.191 | 0.203 | 539 | +27 |
| monthly | **seasonal_naive** | **0.169** | **0.153** | 1,838 | +1,563 |
| monthly | moving_average | 0.386 | 0.436 | 4,388 | +333 |
| monthly | ses | 0.391 | 0.456 | 4,469 | +491 |

## Discussion

**Per-series vs. portfolio rankings disagree, and that disagreement is itself the finding.** At the individual product x location level, Seasonal Naive wins decisively at every grain (lowest sMAPE by a wide margin) — for a single sparse, intermittent series, "what happened on this exact date last year" is a far better anchor than a short recent average, which mostly just repeats whatever the last few (often zero) observations were. At the portfolio level, the ranking flips at daily/weekly grain: SES and Moving Average win, because aggregate daily/weekly totals are noisy-but-not-sparse, and a recent-average tracks the current level better than a single noisy day from a year ago. Only at monthly grain does Seasonal Naive also win at the portfolio level, and by a large margin — monthly aggregates are where the underlying annual seasonality (confirmed in `01_data_exploration_summary.md` §3: consistent Dec-Mar peak / Jun-Aug trough every year) dominates over short-window noise.

**Seasonal Naive has a structural growth-trend bias, visible at every grain but most severe at monthly.** Bias is consistently positive (actual > forecast) and grows with the aggregation window — daily +52, weekly +374, monthly +1,563 at the portfolio level. This is exactly what you'd expect given the ~14-17% YoY revenue growth found in Deliverable 1: "same period last year" systematically undershoots a series that's still growing, and the undershoot compounds visibly as more periods get summed into one bucket. **This is the single clearest piece of evidence that none of these three baselines — including the best-performing one — should be mistaken for a target**: even Seasonal Naive's strong monthly showing is a biased forecast, not just a noisy one. Phase 3's real model needs an explicit trend term, not just seasonality.

**Practical grain trade-offs, as anticipated in the task brief:**
- **Daily is too noisy for Seasonal Naive at the individual-series level** in the sense that predicts intuition — but not for the reason expected. It actually "wins" on sMAPE (0.038) mostly because most days are legitimately zero for a given SKU x location, and Seasonal Naive predicting zero-when-last-year-was-zero is trivially easy to get right at that scale; this isn't a meaningful accuracy signal, it's an artifact of sparsity. The 73% zero-actual exclusion rate for MAPE is the more honest read: daily grain, per series, is dominated by intermittent/zero demand that none of these baselines are built for (a proper intermittent-demand method like Croston's is out of scope here but worth flagging for Phase 3).
- **Monthly smooths over the peak-season signal that actually matters for a seasonal boating retailer** — with only 12 points/year, Moving Average(3mo) and SES(alpha=0.3) can't react to the sharp Dec-Mar ramp at all (portfolio MAPE 0.44-0.46, roughly triple Seasonal Naive's), while Seasonal Naive does capture it (because it directly encodes "the same month last year") but at the cost of the trend-bias described above.
- **Weekly is the most balanced portfolio-level performer** across baselines (MAPE range 0.18-0.20, the tightest spread of the three grains) and gives the finest resolution that still lets Seasonal Naive/Moving Average smooth over the sparsity that dominates daily — consistent with the task's expectation going in.

## Recommendation

**Weekly grain** looks like the best default for Task 1.1's forecasting unit: it avoids the extreme per-SKU sparsity that makes daily-grain metrics hard to trust, while preserving enough resolution to react faster than monthly to the start/end of the peak season — which matters directly for the 3-month-ahead horizon in Task 1.2 (a 3-month-ahead forecast made at weekly grain gives ~13 update points to react with; at monthly grain it's only 3). The team has since adopted this as the Task 1.1 decision — SKU × location, weekly — matching this recommendation. It should still be revisited once Phase 2 features (calendar/promo/weather) are in place and a real trend-aware model is being evaluated, since a proper model may recover more of daily grain's granularity than these baselines could.

Whichever grain is chosen, **do not treat Seasonal Naive's raw numbers above as the bar to beat** without accounting for its structural growth bias — a fair comparison for Phase 3 should either de-trend Seasonal Naive's forecast or report bias-adjusted accuracy alongside sMAPE.
