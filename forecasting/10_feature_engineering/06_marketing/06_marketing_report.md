# Marketing/Promotion Feature Report — Stage 2 Feature Engineering (Task 2.6)

> Builds on task 2.5's `baseline+calendar+holidays+weather+economic`
> formula. MLflow run
> `baseline+calendar+holidays+weather+economic+marketing`
> (`7a66d958f9cb481692c60d47ec27a35a`) logged under
> `/Shared/01_feature_iteration`; the previous formula is refit in-memory
> only, to compute this task's delta — not re-logged, since task 2.5 already
> logs it.
>
> **Specification.** The formula uses `discount_rate` only; `total_discount_amount` is
> excluded because it is a scale confound (see "Why `total_discount_amount` is excluded"
> below).

## Method

- Same panel/estimator/train-holdout split as tasks 2.2–2.5
  (`PanelOLS(entity_effects=True)`, entity = `(product_variant_id,
  location_id)`, train 2020–2024, holdout 2025, `trend` control present).
- **Scoped to `stg_orders.discount_amount` only**, per the team decision made
  before this stage started: no campaign/promotion table or marketing-spend
  data exists anywhere in this project.
- Queried directly from the shared prod catalog's `stg_orders`
  (`lh_nautical.staging.stg_orders`, `status in ('paid', 'confirmed')`,
  matching the "valid revenue" convention `fact_demand_daily`/
  `agg_sales_daily` already use) — **no dbt model changes**, consistent with
  this workstream's established "exploratory, not a committed dbt model"
  convention.
- **Aggregated to (location, week), not (product, location, week)**: an
  order's `discount_amount` is order-level, not line-item-level, and
  allocating it across an order's line items would need an arbitrary
  pro-rata rule this task doesn't need — the hypothesis ("discount events
  lift short-term volume") is naturally a location-week-level signal (a
  store ran a promotion), broadcast to every product sold at that location
  that week, the same way weather/economic features are broadcast.

## Why `total_discount_amount` is excluded (scale confound)

Two discount features are candidates: `total_discount_amount` (weekly sum,
currency) and `discount_rate` (`total_discount_amount / total_subtotal`). With both in
the formula, both show **t-stats around 44** — larger even than the no-trend SELIC result
in task 2.5 (t = 38.1) — with `discount_rate` **negative** despite its raw correlation with
contemporaneous demand being weakly *positive* (+0.062, see the reverse-causality check
below). Implausible significance combined with a sign that contradicts the simple
correlation is the red flag for a confound.

**Diagnosis**: `total_discount_amount` is a raw sum, mechanically tied to
order volume — a location-week with more orders has more total discount
currency almost by definition, even at a *constant* average discount rate.
It is a volume/scale proxy, not a causal discounting signal, and it is
collinear with `discount_rate` (same numerator, `total_subtotal` as the only
other input). Including both is a specification error — a different kind of
confound from task 2.5's trend issue (a scale/collinearity artifact, not a
temporal-trend one).

**Specification**: `total_discount_amount` is excluded from the formula.
`discount_rate` (scale-invariant, one degree of freedom, no collinear
partner left in the model) is the only marketing feature tested. See
`add_marketing_features.py`'s comment for the reasoning kept alongside
the code.

## Reverse-causality check (required by this task specifically)

Tests whether discount weeks are timed to *already*-elevated demand (the
marketing team reacting to expected demand, rather than driving it):

| Check | Correlation | n |
|---|---|---|
| `discount_rate` vs. same-week demand | +0.062 | 1,878 location-weeks |
| `discount_rate` vs. prior-week demand | +0.070 | 1,878 location-weeks |

**Both correlations are weak and similar in magnitude** — discount timing
does not show a meaningfully stronger relationship with *past* demand than
with *contemporaneous* demand, which is what a reverse-causality pattern
(discounts chasing already-known high demand) would predict. This doesn't
rule out reverse causality at a finer grain than location-week, but at this
grain there's no evidence for it — the near-zero correlation in either
direction is consistent with discount timing being close to unrelated to
recent demand, one way or the other.

## Results

| Metric | previous formula | `+marketing` (`discount_rate` only) | % change |
|---|---|---|---|
| RMSE | 1.71187 | 1.71186 | −0.0005% |
| Bias | 0.28122 | 0.28117 | −0.020% |
| MAPE | 0.95943 | 0.95941 | **−0.0016%** |
| sMAPE | 1.98928 | 1.98927 | −0.0006% |

**MAPE improvement vs. the previous formula: ~0.00%. Threshold: >2%. Does
not meet the threshold, and not close.** (For comparison: the fit with
`total_discount_amount` and `discount_rate` together shows a misleadingly large
0.38% improvement — the second-best in the chain after calendar — entirely
attributable to the scale confound described above, not to a real
marketing effect.)

`discount_rate` coefficient: **−0.0304, t = −1.61, p = 0.106 — not
significant.** A believable, unremarkable t-stat, unlike t = −44.5 when
`total_discount_amount` is also in the formula.

## Discussion

With the scale confound removed, this task's result is a clean,
unremarkable null: discount rate has no statistically detectable effect on
demand at the location-week grain, and no accuracy improvement. This is
consistent with (though doesn't prove) genuinely weak or absent
discount-driven demand at this aggregation level — it's also consistent with
the order-level discount signal simply being too diluted once broadcast
uniformly across every product at a location, since the true effect (if any)
is likely product- or category-specific rather than a location-wide average.
That is a limitation of the order-to-panel allocation described in Method,
not evidence the underlying discount events had zero effect on any specific
product.

## Recommendation — Checkpoint

**Not kept** — `discount_rate` does not clear the >2% MAPE-improvement bar
(≈0%) and is not statistically significant. The reverse-causality check
found no evidence discounts are timed to already-elevated demand at this
grain, so the negative result here reflects an absent/undetectable effect
rather than a masked reverse-causality artifact.

**Carried forward into the cumulative formula for task 2.7** under the
conservative-default policy — no specific confound mechanism between
discount timing and inventory/stockout features has been identified. The task 2.10
ablation drops the marketing layer (`10_frozen_feature_set.md`).
