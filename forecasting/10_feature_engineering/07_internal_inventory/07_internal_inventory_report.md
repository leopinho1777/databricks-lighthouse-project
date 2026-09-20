# Internal/Inventory Feature Report — Stage 2 Feature Engineering (Task 2.7)

> Builds on task 2.6's `baseline+calendar+holidays+weather+economic+marketing`
> formula. **No new MLflow run was logged for this task** — see "The
> stockout signal is not testable with this instrument" below. This differs from
> the other tasks by design: there is no valid test to log.

## Method and two exclusions decided before fitting anything

This task tests two possible feature groups per the tracker: inventory
signals (stockout/censoring) and price-change. Both existing candidates were
excluded before any regression was attempted, for two **different** reasons
that should not be conflated:

1. **`is_demand_censored_flag` is target leakage, not a candidate to test.**
   Per `02_schema_design/fact_demand_daily_prototype.sql:125`:
   `is_demand_censored_flag = coalesce(qty_sold_gross, 0) >= stock_on_hand`
   — it is computed directly from the *same day's* `qty_sold_gross`, which is
   (up to returns) this task's own target variable. Fitting it as a
   regressor could look informative purely because it partially encodes the
   answer, and it would be unusable in deployment regardless: next week's
   actual `qty_sold_net` is never available ahead of time to compute it
   from. This is categorically different from a confound (an external
   variable that happens to correlate with the target through some
   mechanism, like tasks 2.5's trend/SELIC or 2.6's discount-volume cases) —
   it doesn't produce a "suspicious t-stat" for a post-hoc check to catch,
   it's simply not a valid input. Excluded outright, not tested and reported
   as "not significant" (that would misrepresent what happened). It's
   reported below only as a descriptive statistic, which is valid context.
2. **Price-change is dropped for data-availability reasons**, confirmed in
   `00_feature_backlog.md`: `dim_products` has only a single current price
   per variant, no price history anywhere in the project. This is a
   different problem from #1 — even if price history existed, a
   current-price feature would carry its own, different issue (joint
   determination/endogeneity: price and demand are set simultaneously, so
   causal direction between them is genuinely ambiguous), not a
   target-leakage issue. Both exclusions happen to remove inventory/price
   signals from this task, but for unrelated reasons, and only #1 involves
   data this project actually has.

`is_stockout_day` (`stock_on_hand == 0`, derived purely from the
forward-filled stock snapshot series — independent of `qty_sold_gross`/
`qty_sold_net`, so no leakage concern) was the one feature planned to
actually be tested — see next section for why it also couldn't be.

## The stockout signal is not testable with this instrument, not merely "not significant" — a distinction that matters

Aggregating `is_stockout_day`/`is_demand_censored_flag` to weekly `_fraction`
columns and checking real data coverage (before filling missing data with
0.0) found:

| Check | Value |
|---|---|
| Entities in the panel | 6,054 |
| Entities that ever received *any* stock snapshot | 1,403 (23.2%) |
| Entities that ever show a stockout day | **3** |
| Rows (product×location×week) with any stock data at all | 1.32% |
| Rows flagged as a stockout | 0.0016% |
| Weeks flagged as demand-censored (descriptive only) | 0.01% |

`PanelOLS(entity_effects=True)` estimates a feature's coefficient from
**within-entity variation only** — an entity whose `stockout_day_fraction`
never changes over its whole history contributes nothing to that estimate,
regardless of its row count. With only 3 of 6,054 entities ever showing any
variation at all, a fitted coefficient would be driven entirely by those 3
series — not a credible population-level estimate, and not a fair test of
the underlying hypothesis *as estimated by this particular instrument*.
Attempting the fit anyway (confirmed empirically) raises `linearmodels`' own
rank-deficiency error (`exog does not have full column rank`), which is
itself informative: it's the model correctly refusing to produce a
coefficient from data this degenerate, rather than silently returning an
unstable one.

**Precise framing, not to be lost in a later summary**: this is a limitation
of the entity-fixed-effects design specifically (it can only use
within-entity variation, and 76.8% of entities offer none), not proof that
stockout timing has no relationship to demand at all. A specification that
can use between-entity variation too — e.g. pooled OLS without entity
effects, or a between/random-effects estimator — might still be testable
with the same 1,403-entity subset that has any stock data, just not with
this shared regression's current fixed-effects design. Rebuilding the
estimator is out of scope for this checkpoint (this workstream's
measuring instrument was fixed by design at task 2.2 to isolate
population-level effects via entity fixed effects, and changing that
mid-chain would undermine every prior task's comparability), so the correct
conclusion here is **"not testable with this instrument's fixed-effects
design," not a bare "not testable"** — the latter risks being read later as
"stock data has no signal here," when the more precise statement is "we
don't yet have the right-shaped test for it."

**This also confirms — with hard numbers, not just a restated caveat — the
sparse-snapshot concern already flagged in Phase 1** (stock history has
"~1.2 real snapshots per pair," `01_data_exploration_summary.md` flag #3;
also noted as a still-open, deferred item in `OVERVIEW.md`'s stage-01
summary: "the stock-history sparsity from `01`... deferred rather than
solved"): stock history in this dev dataset isn't a real time series for
the vast majority of the catalog, it's at most a single stale point-in-time
reading. **A "not tested with this instrument" conclusion is the honest one
here — not a "not kept" verdict**, which would misleadingly imply a valid
test happened and failed. No new MLflow run was logged: there is no viable
feature to report a test result for.

## The tracker's censored-demand check

The tracker's task 2.7 asks to "check whether `qty_sold_net` was ever capped
by stock-on-hand... and correct for this before using inventory features."
The check is run in `02_schema_design` and repeated here: censoring is flagged on only
0.01% of product-location-weeks in this dataset. **No censoring adjustment is needed or
possible with current data**
— there isn't a meaningful population of censored periods to adjust, and
the underlying reason (near-total absence of real stock snapshots) cannot be
addressed by a modeling choice. This is the check the tracker asks for: the
conclusion is "not applicable at current data density," reached by measurement, not
assumed.

## Recommendation — Checkpoint

**No feature added, and no MAPE/threshold verdict to report** — inventory
features are excluded not because they failed a test, but because no valid
test was possible with current data (`is_demand_censored_flag`) or because
there isn't enough real variation to trust a result (`is_stockout_day`,
confirmed empirically). Price-change remains excluded for the
data-availability reason above.

**Carried forward unchanged into task 2.8**: the cumulative formula for the
COVID-anomaly investigation (independent of this chain) and for task 2.9's
VIF check is `baseline+calendar+holidays+weather+economic+marketing` — the
same formula task 2.6 produced, since task 2.7 added nothing to it.

**For task 2.10**: this task contributes no ablation candidate (nothing was
added to ablate). It is recorded in `10_frozen_feature_set.md` §5 as "internal/inventory
data was not testable with this stage's fixed-effects instrument", distinct from the "not
kept despite a valid test" verdicts for calendar, holidays, weather, economic, and
marketing.

**Three distinct outcomes appear across tasks 2.5–2.7, and
`10_frozen_feature_set.md` keeps them separately labeled rather than collapsing them into
"didn't work":**
- **Confound** (task 2.5's SELIC/trend, task 2.6's discount-amount/volume):
  real data, a real fit, wrong interpretation without the right control.
  Can resurface as a genuine finding with the right control — SELIC does, partially,
  once trend is included.
- **Leakage** (`is_demand_censored_flag`, this task): shouldn't be fit at
  all, definitionally — never becomes usable in this form regardless of
  data volume or estimator choice.
- **Untestable-with-this-instrument** (`is_stockout_day`, this task): could
  technically be forced to fit, but the result wouldn't mean anything given
  this estimator's within-entity identification requirement. Might become
  testable later, either with a different (non-fixed-effects) specification
  or if stock-snapshot density improves — this ties back to the
  stock-history-sparsity item flagged in Phase 1
  (`01_data_exploration_summary.md`, `OVERVIEW.md`'s stage-01 summary) and
  is recorded in `10_frozen_feature_set.md` as: **stock-derived
  features remain untested for demand modeling, for reasons distinct from
  (but related to) the Phase 1 sparse-snapshot finding** — not
  "found to have no effect."
