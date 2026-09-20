# Feature Backlog and Method — Stage 2 Feature Engineering (Task 2.1)

One row per candidate feature group, with a one-sentence causal hypothesis for why it
should move demand for a Brazilian nautical/boating retailer (product categories
include outboard motors, marine electronics/GPS/sonar, life jackets, anchors, ropes,
antifouling paint — see `dbt/seeds/seed_category_fix.csv`). Each hypothesis is written
before the feature is tested so the production set only keeps features that can be
explained to the client, not correlations that cannot be justified (task 2.1's stated
goal). Each group is tested as one cumulative addition to the pooled panel regression
in tasks 2.2–2.7; the last column records the data-availability decision behind it.

| # | Feature group | Candidate features | Causal hypothesis | Data availability note |
|---|---|---|---|---|
| 1 | Calendar / seasonality | week-of-year, month, quarter, day-of-week, is_weekend | Boating is a leisure activity tied to the Southern-hemisphere summer (Nov–Feb) and weekends, when people actually go out on the water and buy/replace gear beforehand. | Mostly in `dim_calendary` (`year`, `month`, `quarter`, `day_of_week`); week-of-year and `is_weekend` derived from `date_day` in-script. |
| 2 | Holidays | public holiday flag, long-weekend flag | Brazilian holidays (Carnival, Corpus Christi, national holidays that create long weekends) cluster leisure travel and boat outings, driving pre-holiday purchases of safety/consumable gear. | Not present anywhere in the project. Sourced via the `holidays` Python package (`holidays.Brazil()`), as the tracker suggests. |
| 3 | Weather | temperature, precipitation, wind speed | Bad weather (rain, high wind) suppresses actual boating trips and therefore near-term replacement/consumable purchases (ropes, antifouling paint, safety gear); may duplicate the season signal already in calendar features — tested explicitly for redundancy in task 2.9. | Not present anywhere in the project. Sourced via Open-Meteo's free historical archive API, joined on a small manual `location_id → (lat, lon)` lookup since `dim_locations` has no coordinates. |
| 4 | Economic indicators | SELIC (interest rate), IPCA (inflation) | Boats and marine equipment are discretionary/leisure purchases, so demand should be sensitive to the cost of credit (SELIC) and to inflation eroding disposable income (IPCA) at the national level. | Not present anywhere in the project (only FX rates exist, used for currency conversion, not as a demand driver). Sourced via BCB's free SGS API (Brazil-specific, not the tracker's literal FRED/US suggestion — confirmed with the team since this is a Brazilian business). |
| 5 | Marketing / promotions | discount rate (order-level) | Discount events should lift short-term volume, but discounts may be timed to demand the business already expected (reverse causality) — tested explicitly in task 2.6. | No campaign/promotion table or marketing-spend data exists anywhere in the project. Scoped to `stg_orders.discount_amount` only (computed in staging, dropped before `fct_sales`); "campaign spend" is out of scope — confirmed with the team. |
| 6 | Internal / inventory | stockout flag, demand-censoring flag | A product that is out of stock cannot be sold, so raw `qty_sold_net` on stockout days/weeks understates true demand — feeding that straight into the model would teach it to under-forecast. | Available as `fact_demand_daily.is_stockout_day` / `is_demand_censored_flag`, but the stock snapshots are sparse (~1.2 per product×location pair, see `02_schema_design`), so the flags are used with that caveat stated. Price-change (also requested by the task) is out of scope: `dim_products` has only a single current price per variant, no price history — confirmed with the team. |

## Data-gap decisions (confirmed with the team)

- **Economic (row 4)**: use BCB SGS (Brazil) instead of the tracker's literal FRED
  (US) suggestion — FRED data has no causal relationship to a Brazilian retailer's
  demand.
- **Marketing (row 5)**: scope to `stg_orders.discount_amount` only. No campaign or
  marketing-spend data exists anywhere in this project.
- **Internal/inventory (row 6)**: exclude the price-change sub-feature. No price-history
  or price-snapshot model exists anywhere in this project — `dim_products` carries
  only the current `sale_price`/`cost_price`, so "price changes over time" cannot be
  computed from existing data without building a new price-history model, which is
  out of scope for this stage.

## Structural control: linear time trend

**`trend` (weeks elapsed since the panel's first period) is a permanent,
always-present term in `_shared/panel_regression.py`'s `fit_and_evaluate()`,
applied to every task from 2.2 onward. It is not a candidate feature.** It gets no
keep/drop verdict, no row or causal hypothesis in the feature table above, and it is
not subject to the cumulative-retention policy below — that policy is about whether
to keep testing on top of a candidate feature that did not earn its own place, and
`trend` is not a candidate for the production set. It exists so every *other*
feature's coefficient can be read as its own effect rather than a proxy for time.

**Why it is needed.** `PanelOLS(entity_effects=True)` only absorbs each entity's own
average level — nothing in the model represents a trend shared across the whole
panel over time. The business grows ~14–17% a year, smoothly
(`03_granularity_baselines`), so any slowly drifting (not just cyclically varying)
covariate tested without this control can pick up that growth instead of, or in
addition to, its own effect. The sensitivity check that shows this is the economic
task (`05_economic/05_economic_report.md`): without a trend term, `selic_rate` has a
coefficient of +0.00266 (t = 38.1, wrong sign) and a 0.48% MAPE improvement, the
closest of any task to the 2% bar; with the trend term it is −0.00040 (t = −3.37,
correctly signed) and the improvement is 0.023%. `ipca_monthly_variation` loses
significance entirely — its apparent effect without the control is essentially all
trend.

**Why a single linear term, not a per-year or per-week fixed effect.** (1) The growth
is smooth and consistent year over year, so a linear term in log-space (the target is
`log1p(qty_sold_net)`) has the right shape for roughly constant-percentage growth.
(2) A per-period time fixed effect would saturate the time dimension and make every
other time-varying feature (calendar, holidays, weather, economic) unidentifiable; a
single trend column leaves all within-year and cyclical variation intact for the
other features to explain.

**Effect on the earlier tasks.** With the control in place, calendar's month
coefficients are essentially unchanged (calendar is not confounded with trend), while
holidays' terms and part of the weather terms lose significance — a more modest
version of the same effect, even though those variables are nominally cyclical. All
numbers in this document and in the task reports include the trend control.

## Method: cumulative testing and the retention policy

Tasks 2.2–2.7 are cumulative by design: each task tests its own marginal contribution
against the *full* accumulated formula, regardless of whether every earlier layer
cleared its own >2% MAPE-improvement threshold. **"Stays in the testing chain" and
"kept in the final production feature set" are different questions**, and
`10_frozen_feature_set.md` keeps them separate.

The retention policy rests on two different justifications, and each task states which
one applies:

1. **A specific, named confound** (the strong case): dropping the earlier layer would
   let a later feature's coefficient absorb variance the earlier layer actually
   explains. This applies to calendar→holidays: holidays cluster by month (Carnival in
   Feb/Mar, Christmas/New Year in Dec/Jan) and month is already a strong predictor, so
   removing the month control before testing holidays would let the holiday
   coefficient inflate with general seasonal variance that calendar, not holidays,
   explains. It is the only layer pair with a concrete, verified mechanism.
2. **Conservative default retention** (the weak case, used when no specific confound
   has been identified): carrying an inert layer forward costs little relative to
   re-deriving and testing confound-freeness at every step, so the default is to
   retain rather than drop, on cost-effectiveness grounds — not because a mechanism
   was found. This is the justification for retaining holidays going into weather:
   no specific mechanism by which dropping holidays would bias a weather coefficient
   has been identified (holiday dates are fixed by the calendar, independent of actual
   weather, and any purely seasonal confound is already absorbed by the month terms).

The final production set is decided by an ablation on the assembled formula, one layer
at a time (`10_frozen_feature_set.md`): the final formula with and without each layer
that stayed in the chain without clearing its own threshold. A layer whose removal does
not hurt accuracy is dropped from the production set even though it stayed in the
testing chain.

## Results by task

Each result is logged as a genuine positive or negative result. All figures include the
trend control.

- **Task 2.2 (calendar)**: does not clear the threshold on its own (0.60% MAPE
  improvement over the trend-controlled zero-feature reference) despite highly
  significant, theoretically consistent month coefficients. Retained as a seasonal
  control. See `02_calendar/02_calendar_report.md`.
- **Task 2.3 (holidays)**: does not clear the threshold (≈0% net MAPE change).
  `has_holiday` and `is_long_weekend` are both non-significant — a clean negative
  result. Retained in the chain under the conservative-default justification. Without
  the trend control both terms are significant with opposite signs, which reads as
  "roughly cancel out" but is a trend artifact. See `03_holidays/03_holidays_report.md`.
- **Task 2.4 (weather)**: does not clear the threshold (≈0% net MAPE change).
  `temp_mean` is negative and non-significant, `wind_max` is significant only at the
  margin (p = 0.046), the holiday terms retested here stay non-significant, and
  `precip_sum` is never significant. Without the trend control `temp_mean` and
  `wind_max` are both significant (`temp_mean` positive). Retained in the chain for
  task 2.5 under the conservative-default justification. See
  `04_weather/04_weather_report.md`.
- **Task 2.5 (economic)**: does not clear the threshold. `selic_rate` −0.00040
  (t = −3.37), MAPE improvement 0.023%; `ipca_monthly_variation` is not significant.
  `selic_rate`'s small, correctly signed effect is a genuine (if practically minor)
  finding, distinct from the accuracy verdict. See `05_economic/05_economic_report.md`.
  Retained in the chain for task 2.6 under the conservative-default justification.
- **Task 2.6 (marketing)**: does not clear the threshold (≈0% net MAPE change). The
  specification uses `discount_rate` only. `total_discount_amount` (raw sum) is
  excluded because it is mechanically tied to order volume (more orders → more total
  discount currency regardless of any real discounting effect) and collinear with
  `discount_rate`: with both terms in the formula the t-statistics are around 44 each,
  an artifact of scale, and the apparent 0.38% MAPE gain is the same artifact.
  `discount_rate` alone is unremarkable (t = −1.61, p = 0.106). The required
  reverse-causality check finds weak, similar-magnitude correlations between
  `discount_rate` and both same-week (+0.062) and prior-week (+0.070) demand — no
  evidence discounts are timed to already-elevated demand at this grain. See
  `06_marketing/06_marketing_report.md`. Retained in the chain for task 2.7 under the
  conservative-default justification.
- **Task 2.7 (internal/inventory): not tested — a different outcome from every other
  task, and the distinction matters.** `is_demand_censored_flag` is target leakage
  (`= coalesce(qty_sold_gross, 0) >= stock_on_hand`, derived from the same day's own
  sales) and is excluded outright, never fit. `is_stockout_day` has no leakage
  concern, but only 3 of 6,054 entities ever show any stockout (1,403 entities, 23.2%,
  have any stock snapshot at all — matching the "~1.2 real snapshots per pair" finding
  of `01_data_exploration` with hard numbers), so `PanelOLS(entity_effects=True)`'s
  within-entity estimate would be driven by 3 series; `linearmodels` confirms this with
  its own rank-deficiency error. **The precise framing is "not testable with this
  fixed-effects instrument", not a bare "not testable"**: a specification that uses
  between-entity variation (e.g. pooled OLS) could still test it on the 1,403 entities
  that have stock data. There is no MAPE/threshold verdict, no MLflow run, and nothing
  is added to the cumulative formula. Price-change remains excluded for the
  data-availability reason above. See `07_internal_inventory/07_internal_inventory_report.md`,
  which also separates the three distinct outcomes seen across tasks 2.5–2.7
  (confound / leakage / untestable with this instrument) that `10_frozen_feature_set.md`
  keeps labeled separately.

## Cross-task pattern: the per-layer threshold is nearly unreachable at this grain

No layer clears the >2% MAPE-improvement bar. The absolute distances make that
concrete:

- Threshold interpretation used throughout: **relative** improvement,
  `(prev_mape - new_mape) / prev_mape > 0.02`. The tracker's phrasing ("e.g., >2% MAPE
  gain") does not disambiguate relative from absolute (percentage-point) improvement.
  At this project's MAPE level (≈0.96, i.e. ≈96%) the two readings are numerically
  close (2 points absolute ≈ 2.08% relative off a ~96-point base), so the ambiguity
  does not change any verdict — every task misses by an order of magnitude under
  either reading.
- What one task needs, in absolute terms, off a ~0.965 MAPE base: roughly a 0.0193
  absolute MAPE reduction (relative 2% of 0.965).
- Observed absolute MAPE change per task (trend control present in every run,
  including the reference):
  - Task 2.2 (calendar): **−0.0058** — the largest improvement in the chain, still
    only ~30% of the ~0.0193 needed to pass individually.
  - Task 2.3 (holidays): **+0.00004** (negligibly worse).
  - Task 2.4 (weather): **+0.00015** (negligibly worse).
  - Task 2.5 (economic): **−0.00022** (0.023% relative).
  - Task 2.6 (marketing): **−0.000015** (0.0016% relative).
  - Cumulative, all five layers vs. the trend-controlled zero-feature reference:
    **−0.0058** (0.60% relative) — adding holidays, weather, economic and marketing on
    top of calendar contributes essentially nothing net; the entire cumulative gain
    is attributable to calendar alone.

**Interpretation.** The panel is 92.9%-zero at the individual product×location×week
level (consistent with `04_demand_classification`'s Intermittent/Lumpy finding), so
MAPE here is dominated by idiosyncratic low-count noise that a linear covariate group
cannot touch. Two independent signals point the same way: the marketing task, with a
narrow single-column scope, fails the threshold for the structural reason above, and
every effect that survived proper specification is small. That is evidence for "little
real signal at this grain" over "real small effects sitting just under a too-strict
bar". This is the leading explanation, not a settled conclusion: a real,
non-confounded effect that cleared a meaningful fraction of the threshold would count
against it.

**The other candidate explanation also stands**: the >2% threshold may be poorly
calibrated for this MAPE regime. A 2%-relative bar off a ~96% MAPE base is a much
larger absolute ask (~1.93 points) than the same relative bar would be off a smaller,
better-behaved MAPE (2% of a 20% MAPE is only 0.4 points). Applying one fixed relative
threshold per individual layer, at this grain, may make it structurally near-impossible
for *any* single feature group to pass on its own, independent of whether the feature
is useful.

**Open decision for the team**: whether the right test is "does each individual layer
clear 2% on its own" (the practice used here; every layer fails it) or "does the *fully
cumulative* final formula clear 2% against the zero-feature/Phase 1 baseline" (0.60%
after five layers, so this reframing alone would not produce a pass, but it is a
materially different and more defensible question at this grain). Every task's
individual result is logged either way, because that information feeds the client
narrative and the ablation in `10_frozen_feature_set.md`.

## Not part of the cumulative chain

COVID anomaly (task 2.8) and multicollinearity (task 2.9) are not candidate features:
they are a separate anomaly investigation and a diagnostic check on the weather terms,
scoped directly in the task tracker.

- **Task 2.8 (COVID anomaly)**: three independent checks (Phase 1's revenue-based
  annual comparison, a quantity-based reconciliation with a monthly seasonal-shape
  overlay, and a residual check from task 2.2's `baseline+calendar` model) find no
  detectable 2020–2021 anomaly in level, shape, or model residuals. Recommendation:
  **flag, don't exclude or down-weight** — no training-window change. See
  `08_covid_anomaly/08_covid_anomaly_report.md`.
- **Task 2.9 (multicollinearity)**: VIF on the weather terms is **low** in both the
  calendar-only scope (1.17–1.49) and the full task 2.6 formula plus trend
  (1.19–1.55) — nowhere near the 5.0 threshold, so the ridge fallback is not
  triggered. `wind_max`'s counter-intuitive positive sign and marginal significance
  (p = 0.046) is therefore **not** explained by redundancy with calendar or anything
  else in the formula; it remains a genuine, unresolved result. See
  `09_multicollinearity_check/09_multicollinearity_report.md`.
- **Calendar term collinearity** (a secondary result of task 2.9): calendar's month
  dummies and `week_of_year_sin`/`week_of_year_cos` are highly collinear (VIF up to
  44). That is the likely reason `week_of_year_sin` is persistently near-non-significant
  in tasks 2.2–2.6: it is largely redundant with the month dummies, not evidence that
  weekly seasonality beyond month level does not exist. `10_frozen_feature_set.md`
  cites it and decides the Fourier terms with a direct holdout ablation.

## Data types

`discount_rate` is cast to `float` at the source (`06_marketing/add_marketing_features.py`)
because the SQL connector returns it as `Decimal` (object dtype), which pandas
arithmetic such as the VIF computation rejects. Every feature column fed into
`PanelOLS` in tasks 2.2–2.7 was checked directly (`.dtype` on the fitted DataFrame):
`discount_rate` and `total_discount_amount` are the only columns that ever arrive as
`object`/`Decimal`; every other feature (`qty_sold_net` itself; the calendar, holiday
and inventory columns, which are pandas- or SQL-`cast(... as double)`-derived; the
weather and economic columns, which come from JSON APIs or an explicit `.astype(float)`)
is `float64` from the start.
