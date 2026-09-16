# Feature Backlog — Stage 2 Feature Engineering (Task 2.1)

One row per candidate feature group, with a one-sentence causal hypothesis for why it
should move demand for a Brazilian nautical/boating retailer (product categories
include outboard motors, marine electronics/GPS/sonar, life jackets, anchors, ropes,
antifouling paint — see `dbt/seeds/seed_category_fix.csv`). The point of writing the
hypothesis first is to only keep features we can explain to the client, not
correlations we can't justify (task 2.1's stated goal). Each group is tested as one
cumulative addition to the pooled panel regression in tasks 2.2–2.7; the last column
notes any data-availability caveat resolved before this backlog was written.

| # | Feature group | Candidate features | Causal hypothesis | Data availability note |
|---|---|---|---|---|
| 1 | Calendar / seasonality | week-of-year, month, quarter, day-of-week, is_weekend | Boating is a leisure activity tied to the Southern-hemisphere summer (Nov–Feb) and weekends, when people actually go out on the water and buy/replace gear beforehand. | Mostly in `dim_calendary` (`year`, `month`, `quarter`, `day_of_week`); week-of-year and `is_weekend` derived from `date_day` in-script. |
| 2 | Holidays | public holiday flag, long-weekend flag | Brazilian holidays (Carnival, Corpus Christi, national holidays that create long weekends) cluster leisure travel and boat outings, driving pre-holiday purchases of safety/consumable gear. | Not present anywhere in the project. Sourced via the `holidays` Python package (`holidays.Brazil()`), exactly as the tracker suggests. |
| 3 | Weather | temperature, precipitation, wind speed | Bad weather (rain, high wind) suppresses actual boating trips and therefore near-term replacement/consumable purchases (ropes, antifouling paint, safety gear); may simply duplicate the season signal already in calendar features — tested explicitly for redundancy in task 2.9. | Not present anywhere in the project. Sourced via Open-Meteo's free historical archive API, joined on a small manual `location_id → (lat, lon)` lookup since `dim_locations` has no coordinates. |
| 4 | Economic indicators | SELIC (interest rate), IPCA (inflation) | Boats and marine equipment are discretionary/leisure purchases, so demand should be sensitive to the cost of credit (SELIC) and to inflation eroding disposable income (IPCA) at the national level. | Not present anywhere in the project (only FX rates exist, used for currency conversion, not as a demand driver). Sourced via BCB's free SGS API (Brazil-specific, not the tracker's literal FRED/US suggestion — confirmed with the team since this is a Brazilian business). |
| 5 | Marketing / promotions | discount amount (order-level) | Discount events should lift short-term volume, but discounts may just be timed to demand the business already expected (reverse causality) — tested explicitly in task 2.6. | No campaign/promotion table or marketing-spend data exists anywhere in the project. Scoped to `stg_orders.discount_amount` only (computed in staging, currently dropped before `fct_sales`); "campaign spend" is out of scope — confirmed with the team. |
| 6 | Internal / inventory | stockout flag, demand-censoring flag | A product that's out of stock can't be sold, so raw `qty_sold_net` on stockout days/weeks understates true demand — feeding that straight into the model would teach it to under-forecast. | Available as `fact_demand_daily.is_stockout_day` / `is_demand_censored_flag`, but flagged unreliable in `02_schema_design` due to sparse stock snapshots (~1.2 per product×location pair) — used with that caveat restated, not silently trusted. Price-change (also requested by this task) is dropped: `dim_products` has only a single current price per variant, no price history anywhere in the project — confirmed out of scope with the team. |

## Data-gap decisions made before this backlog (confirmed with the team)

- **Economic (row 4)**: use BCB SGS (Brazil) instead of the tracker's literal FRED
  (US) suggestion — FRED data would have no causal relationship to a Brazilian
  retailer's demand.
- **Marketing (row 5)**: scope to `stg_orders.discount_amount` only. No campaign or
  marketing-spend data exists anywhere in this project.
- **Internal/inventory (row 6)**: drop the price-change sub-feature. No price-history
  or price-snapshot model exists anywhere in this project — `dim_products` carries
  only the current `sale_price`/`cost_price`, so "price changes over time" cannot be
  computed from existing data without building a new price-history model, which is
  out of scope for this stage.

## Structural control: linear time trend (added after task 2.5's checkpoint)

**`trend` (weeks elapsed since the panel's first period) is a permanent,
always-present term in `_shared/panel_regression.py`'s `fit_and_evaluate()`,
applied to every task from 2.2 forward (retroactively refit into 2.2–2.5).
It is not a candidate feature.** It gets no keep/drop verdict, no row or
causal hypothesis in the feature table above, and it is explicitly **not**
subject to the cumulative-retention policy debate below (the
strong-confound-vs-conservative-default distinction) — that debate is about
whether to keep testing on top of a candidate feature that didn't earn its
own place; `trend` was never a candidate feature being tested for the
production set in the first place. It exists purely so every *other*
feature's coefficient can be trusted as its own effect rather than a proxy
for time.

**Why it was needed**: `PanelOLS(entity_effects=True)` only absorbs each
entity's own average level — it has nothing representing a trend shared
across the whole panel over time. This project's own Phase 1 finding
(`03_granularity_baselines`: the business grows ~14–17%/year, smoothly) means
any slowly-*drifting* (not just cyclically-varying) covariate tested without
this control risks picking up that growth trend instead of, or in addition
to, its own genuine effect. This was discovered empirically in task 2.5: a
much smaller (~85% reduction), correctly-signed SELIC effect replaced what
the pre-fix version had shown as an implausible, wrong-signed coefficient
with a t-stat an order of magnitude larger than anything else in the chain.
See `05_economic/05_economic_report.md`.

**Why a single linear term, not a per-year or per-week fixed effect**: (1)
the growth was already found to be smooth and consistent year over year, not
lumpy, so a linear term in log-space (the target is `log1p(qty_sold_net)`)
is the correctly-shaped control for a relationship already shown to be
roughly constant-percentage growth; (2) a per-period time fixed effect would
saturate the time dimension and make every other time-varying feature
(calendar, holidays, weather, economic) unidentifiable — a single trend
column leaves all within-year and cyclical variation intact for every other
feature to explain.

**Retroactive re-verification, not assumed**: tasks 2.2–2.4 were refit with
the trend control to confirm whether their verdicts held, rather than
assuming cyclical variables would be unaffected. Result: calendar's month
coefficients were essentially unchanged (not confounded with trend), but
**holidays' and part of weather's terms lost significance once trend was
controlled** — a more modest version of the same confound, not assumed away
just because those variables are nominally cyclical. See each task's report
for the corrected numbers.

## Methodological note carried forward to task 2.10

**General principle (applies to every task 2.2–2.7, not just calendar):**
tasks 2.2–2.7 are cumulative by design — each task tests its own marginal
contribution against the *full* accumulated formula so far, regardless of
whether every earlier layer individually cleared its own >2%
MAPE-improvement threshold. **"Stays in the testing chain" and "kept in the
final production feature set" are different questions — do not conflate them
in `10_frozen_feature_set.md`.**

This principle rests on two *different* justifications, and each task should
say which one applies rather than inherit the label without checking:

1. **A specific, named confound** (the strong case): dropping the earlier
   layer would let a later feature's coefficient absorb variance the earlier
   layer actually explains. This was concretely true for calendar→holidays:
   holidays cluster by month (Carnival in Feb/Mar, Christmas/New Year in
   Dec/Jan) and month is already a strong predictor, so removing the month
   control before testing holidays would have let the holiday coefficient
   inflate with general seasonal variance that calendar, not holidays,
   actually explains. This is the only layer-pair checked so far where a
   concrete mechanism was identified and verified.
2. **Conservative default retention** (the weak case, used when no specific
   confound has been identified or checked): carrying an inert layer forward
   costs little relative to fully re-deriving and testing confound-freeness
   at every step, so the default is to retain rather than drop, on
   cost-effectiveness grounds — not because a mechanism was found. This is
   the justification for retaining holidays going into task 2.4 (weather):
   no specific mechanism by which dropping holidays would bias a weather
   coefficient has been identified (holiday dates are fixed by the calendar,
   independent of actual weather realization, and any purely seasonal
   confound is already absorbed by the month terms already in the formula
   from task 2.2) — it is retained as a matter of policy, not because
   omitted-variable bias was demonstrated the way it was for calendar.

Per-task results so far, each logged as a genuine result (positive or
negative) rather than smoothed over. **All numbers below are post-trend-control
(see the section above) — every task was refit, not assumed unaffected:**
- **Task 2.2 (calendar)**: did not clear the threshold on its own (0.60%
  MAPE improvement over the trend-controlled zero-feature reference) despite
  highly significant, theoretically consistent month coefficients — these
  held essentially unchanged after the trend control was added, confirming
  calendar itself was never confounded with trend. Retained as a seasonal
  control. See `02_calendar/02_calendar_report.md`.
- **Task 2.3 (holidays)**: did not clear the threshold (≈0% net MAPE
  change). **Corrected finding**: `has_holiday` and `is_long_weekend` were
  originally both significant with opposite signs (interpreted as "roughly
  cancel out"); once trend is controlled, **neither is significant anymore**
  — a cleaner negative result, not the same finding with smaller numbers.
  Retained in the chain under the conservative-default justification. See
  `03_holidays/03_holidays_report.md`.
- **Task 2.4 (weather)**: did not clear the threshold (≈0% net MAPE change).
  **Corrected finding**: `temp_mean` and `wind_max` were originally both
  significant (`temp_mean` positive); once trend is controlled, `temp_mean`
  flips negative and loses significance, `wind_max` survives only at the
  margin (p = 0.046), and the holiday terms retested here also stay
  non-significant. `precip_sum` was never significant, with or without
  trend. Retained in the chain for task 2.5 under the conservative-default
  justification. See `04_weather/04_weather_report.md`.
- **Task 2.5 (economic)**: did not clear the threshold — and by a much wider
  margin than first reported. **This is the task that surfaced the need for
  the trend control**: pre-fix, `selic_rate` showed an implausible +0.00266
  coefficient (t = 38.1, wrong sign) and a 0.48% MAPE improvement, the
  closest of any task to the 2% bar. Post-fix, `selic_rate` collapses to
  **−0.00040** (t = −3.37, correctly signed) and the MAPE improvement drops
  to **0.023%**. `ipca_monthly_variation` loses significance entirely — its
  apparent effect was essentially all trend. `selic_rate`'s small,
  correctly-signed post-correction effect is a genuine (if practically
  minor) finding worth keeping in the narrative, distinct from the
  accuracy verdict. See `05_economic/05_economic_report.md`. Retained in the
  chain for task 2.6 under the conservative-default justification.
- **Task 2.6 (marketing)**: did not clear the threshold (≈0% net MAPE
  change). **A second confound, caught before reporting this time (not
  after)**: an initial fit with both `total_discount_amount` (raw sum) and
  `discount_rate` showed t-stats around 44 each — larger than task 2.5's
  pre-fix SELIC anomaly — because `total_discount_amount` is mechanically
  tied to order volume (more orders → more total discount dollars,
  regardless of any real discounting effect) and collinear with
  `discount_rate`. Dropped `total_discount_amount` entirely; `discount_rate`
  alone comes back unremarkable (t = −1.61, p = 0.106, not significant).
  Reverse-causality check (required by this task): weak, similar-magnitude
  correlations between `discount_rate` and both same-week (+0.062) and
  prior-week (+0.070) demand — no evidence discounts are timed to
  already-elevated demand at this grain. See
  `06_marketing/06_marketing_report.md`. Retained in the chain for task 2.7
  under the conservative-default justification.
- **Task 2.7 (internal/inventory): not tested, not "not kept" — a different
  outcome from every prior task, and the distinction matters.**
  `is_demand_censored_flag` is target leakage (`= coalesce(qty_sold_gross, 0)
  >= stock_on_hand`, derived from the same day's own sales) and was excluded
  outright, never fit. `is_stockout_day` (no leakage concern) *was* planned
  to be tested, but only 3 of 6,054 entities ever show any stockout at all
  (1,403 entities have any stock snapshot data whatsoever — 23.2% — matching
  Phase 1's "~1.2 real snapshots per pair" finding with hard numbers this
  time), so `PanelOLS(entity_effects=True)`'s within-entity estimate would
  be driven by 3 series — confirmed empirically via `linearmodels`' own
  rank-deficiency error when the fit was attempted. **Precise framing: "not
  testable with this fixed-effects instrument," not a bare "not
  testable"** — a specification that could use between-entity variation
  (e.g. pooled OLS) might still test it with the same 1,403-entity subset
  that has any stock data; this is a limitation of the shared regression's
  design, not proof stockout timing has no relationship to demand. **No
  MAPE/threshold verdict, no MLflow run, and nothing added to the cumulative
  formula for task 2.8** — the formula carried forward is unchanged from
  task 2.6's. Price-change remains excluded for the previously-confirmed
  data-availability reason. See
  `07_internal_inventory/07_internal_inventory_report.md`, which also lays
  out the three distinct failure modes seen across tasks 2.5–2.7 (confound /
  leakage / untestable-with-this-instrument) that `10_frozen_feature_set.md`
  should keep separately labeled.

**Required at task 2.10**: run one explicit ablation on the final assembled
formula for *each* layer that stayed in the chain without clearing its own
threshold (calendar, holidays, and any later layer that ends up in the same
position) — the final formula with vs. without that layer's terms. If
removing a layer doesn't hurt the final model's accuracy, drop it from the
production feature set even though it stayed in the testing chain
throughout. State this distinction explicitly in `10_frozen_feature_set.md`
(control-for-bias-prevention vs. earned-its-place-on-accuracy) for every
layer this applies to.

## Cross-task pattern check (before task 2.7) — the threshold may be nearly
unreachable per-task at this grain, and that needs to be said now

Updated after the trend-control fix and task 2.6's scale-confound fix (all
figures below are post-fix). Five tasks in (calendar, holidays, weather,
economic, marketing), none has cleared the >2% MAPE-improvement bar — and
it's worth quantifying just how far short, rather than treating each as an
isolated surprise:

- Threshold interpretation used throughout: **relative** improvement,
  `(prev_mape - new_mape) / prev_mape > 0.02`. The tracker's own phrasing
  ("e.g., >2% MAPE gain") doesn't disambiguate relative vs. absolute
  (percentage-point) improvement. At this project's actual MAPE level
  (≈0.96, i.e. ≈96%), the two interpretations are numerically close (2
  points absolute ≈ 2.08% relative off a ~96-point base), so **this
  ambiguity does not change any verdict recorded so far** — every task has
  missed by an order of magnitude under either reading — but it should be
  resolved explicitly with the team before task 2.10 applies the threshold
  to the final frozen formula, where the base MAPE may differ.
- What a single task needs, in absolute terms, off a ~0.965 MAPE base:
  roughly a 0.0193 absolute MAPE reduction (relative 2% of 0.965).
- What's actually been observed, absolute MAPE change per task (all with
  trend control present in every run, including the reference):
  - Task 2.2 (calendar): **−0.0058** (the single largest improvement so
    far — still only ~30% of the ~0.0193 needed to individually pass).
  - Task 2.3 (holidays): **+0.00004** (negligibly worse).
  - Task 2.4 (weather): **+0.00015** (negligibly worse).
  - Task 2.5 (economic): **−0.00022** (0.023% relative — down sharply from
    the pre-trend-control 0.48%, now that most of that apparent effect is
    understood to have been the trend itself).
  - Task 2.6 (marketing): **−0.000015** (0.0016% relative, after dropping
    the confounded `total_discount_amount` term — see task 2.6's report;
    the discarded fit would have shown 0.38% here too, the second-largest in
    the chain, entirely from the scale confound).
  - Cumulative, all five layers vs. the trend-controlled zero-feature
    reference: **−0.0058** (0.60% relative) — i.e. adding holidays, weather,
    economic, and marketing on top of calendar has contributed essentially
    nothing net; the entire cumulative gain so far is attributable to
    calendar alone.

**Confirmed, not just predicted**: task 2.6 (marketing, narrow
single-column scope) failed the threshold for the same structural reason
flagged before it ran — the grain itself may be too noisy for any exogenous
covariate to move the needle, regardless of how real the underlying
relationship is. This panel is 92.9%-zero at the individual
product×location×week level (consistent with `04_demand_classification`'s
Intermittent/Lumpy finding), so MAPE here is dominated by idiosyncratic
low-count noise a linear covariate group can't touch. **A second, independent
signal updates confidence toward this explanation**: two of five tasks so
far (economic, marketing) initially showed a large, threshold-adjacent
improvement that turned out to be a confound (trend; then a volume/scale
artifact) rather than a real effect — every genuinely-checked result in this
chain has been small, which is legitimate evidence for "little real signal
at this grain" over "real small effects sitting just under a too-strict
bar," not merely a reframing of the same uncertainty.

**This is the leading explanation so far, not a settled conclusion** — it
rests on n=5 tasks, with 2.7 and the independent 2.8/2.9 checks still ahead.
Task 2.10's write-up should treat it as the current best read, to be
confirmed or overturned by the remaining tasks, not inherited as foregone —
if 2.7 (or a later task) shows a real, non-confounded effect that clears a
meaningful fraction of the threshold, that would be evidence against this
explanation and should be weighted accordingly, not explained away.

**The other candidate explanation stands as originally stated**: the >2%
threshold itself may be poorly calibrated for this specific MAPE regime. A
2%-relative bar off a ~96% MAPE base is a much larger absolute ask (~1.93
points) than the same relative bar would be off a smaller, better-behaved
MAPE (e.g. 2% of a 20% MAPE is only 0.4 points). This isn't a claim the
threshold is simply wrong — it's a flag that applying one fixed relative
threshold per individual layer, at this grain, may make it structurally
near-impossible for *any* single feature group to pass on its own,
independent of whether the feature is useful.

**Not resolved unilaterally — flagged for the team/task 2.10**: whether the
right test is "does each individual layer clear 2% on its own" (current
practice, and every layer has failed it so far) vs. "does the *fully
cumulative* final formula clear 2% against the zero-feature/Phase-1
baseline" (the cumulative result is currently only 0.60% after five layers,
so this reframing alone wouldn't yet produce a pass, but it's a materially
different and more defensible question at this grain). Recommendation:
continue logging each task's individual result exactly as before — that
information stays valuable for the client narrative and for task 2.9/2.10's
ablations regardless of which framing wins — but go into task 2.7 expecting
the same negative-on-accuracy pattern, and raise this framing question with
the team before task 2.10 finalizes the frozen set.

## Not included

COVID anomaly (task 2.8) and multicollinearity (task 2.9) are not candidate features
in the cumulative chain — they're a separate anomaly investigation and a diagnostic
check on task 2.4's weather terms, respectively, and are scoped directly in the task
tracker rather than in this backlog.

**Task 2.8 completed**: three independent checks (Phase 1's original
revenue-based annual comparison, a quantity-based reconciliation with a
monthly seasonal-shape overlay, and a residual check from task 2.2's
already-fitted `baseline+calendar` model) all found no detectable 2020–2021
anomaly in level, shape, or model residuals. Recommendation to the team:
**flag, don't exclude or down-weight** — no training-window change made.
See `08_covid_anomaly/08_covid_anomaly_report.md`.

**Task 2.9 completed**: VIF on weather terms is **low** in both the
calendar-only scope (VIF 1.17–1.49) and the full task 2.6 formula + trend
(VIF 1.19–1.55) — nowhere near the 5.0 threshold, so the ridge fallback was
not triggered. **This directly answers, and does not paper over, the
question task 2.4's report left open**: `wind_max`'s counter-intuitive
positive sign and marginal significance (p = 0.046, post-trend-control) is
**not** explained by redundancy with calendar or with anything else
currently in the formula — it remains a genuine, unresolved result, not an
artifact. This also corrects an overstatement in `04_weather/04_weather_report.md`,
which had claimed (before 2.9 ran) that the trend control alone had
"resolved the puzzle" — task 2.9's low VIF shows that claim doesn't hold;
see that report's correction note.

**Unprompted secondary finding, stated as a citable result, not just
adjacent texture**: calendar's own month-dummy and
`week_of_year_sin`/`week_of_year_cos` terms are highly collinear with each
other (VIF up to 44). This is the likely explanation for a result already
reported across every task in this chain — **`week_of_year_sin`'s
persistent near-non-significance (tasks 2.2–2.6) is very likely because it
is largely redundant with the month dummies already in the model, not
because weekly seasonality beyond month-level doesn't exist.** That's a
real finding about *why* a previously-reported result looks the way it
does, not a new, independent caveat — task 2.10 should cite it as such when
discussing calendar's terms, not file it separately as unrelated context.
Not actionable within this stage's already-checkpointed formula (dropping
either parameterization would be a design change to task 2.2's frozen
formula). See `09_multicollinearity_check/09_multicollinearity_report.md`.

**Latent bug caught while building task 2.9**: `discount_rate`
(task 2.6) was `Decimal`-typed (object dtype) from the SQL connector, which
raised on direct pandas arithmetic in task 2.9's VIF computation —
`linearmodels` had been silently coercing it in every prior fit, masking
the issue. Fixed at the source (`06_marketing/add_marketing_features.py`);
re-ran task 2.6 and confirmed its reported numbers are bit-for-bit
unchanged — a latent type-safety gap, not a numeric error.

**Checked more widely, not just re-confirmed for 2.6**: since silent type
coercion can work fine in several places and misbehave in just one, every
feature column actually fed into `PanelOLS` across tasks 2.2–2.7 was
inspected directly for dtype (`.dtype` on the fitted DataFrame), not just
task 2.6's. Result: `discount_rate`/`total_discount_amount` were the *only*
columns anywhere in the pipeline ever exposed as `object`/`Decimal` — every
other feature (`qty_sold_net` itself; all calendar, holiday, and inventory
columns, which are pandas- or SQL-`cast(... as double)`-derived; weather
and economic columns, which come from JSON APIs or an explicit
`.astype(float)`) was `float64` from the start, with no SQL `DECIMAL`
column in its path to begin with. This was verified empirically (each
column's dtype printed and checked), not inferred from the fact that 2.6's
numbers happened to be unaffected — there was nothing else *to* miscoerce.
