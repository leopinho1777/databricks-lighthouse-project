# Economic Feature Report — Stage 2 Feature Engineering (Task 2.5)

> **Specification.** Every run in the Stage 2 chain includes a linear time-trend term as a
> permanent structural control in `_shared/panel_regression.py`'s `fit_and_evaluate()` (see
> `00_feature_backlog.md`'s dedicated section on this control). This report shows why the
> control is needed: economic indicators are the first features in the chain that drift
> gradually across years, and without the control SELIC's coefficient is implausibly large
> and wrong-signed. With it, SELIC's coefficient shrinks by ~85% and takes the
> theoretically expected sign. MLflow run `baseline+calendar+holidays+weather+economic`
> (`374d3a760208437899320a950df3e3c0`) is logged under `/Shared/01_feature_iteration`; the
> previous formula is refit in-memory only, to compute this task's delta — not re-logged,
> since task 2.4 already logs it.

## Method

- Same panel/estimator/train-holdout split as tasks 2.2–2.4
  (`PanelOLS(entity_effects=True)`, entity = `(product_variant_id,
  location_id)`, train 2020–2024, holdout 2025), with a linear `trend`
  term (weeks elapsed since the panel's first period) as a permanent
  structural control in every run.
- `add_calendar_features()`, `add_holiday_features()`, `add_weather_features()`
  are imported directly from their respective task folders, extending the same
  cumulative chain.
- Economic data sourced from BCB's free SGS API (Banco Central do Brasil),
  not the tracker's literal FRED (US) suggestion, per the team decision made
  before this stage started. Series: **SELIC** (series 432, daily target
  interest rate, % a.a., aggregated to weekly mean) and **IPCA** (series
  433, monthly inflation variation, % — forward-filled to every week within
  its publication month). Both national-level, no location join needed.

## Why the specification includes a trend control (sensitivity check)

**Without the trend control**, `selic_rate` has a coefficient of **+0.00266**
with **t = 38.1** — by far the most extreme result anywhere in this chain
(every other feature's t-stat is in the single-to-low-double digits) — and
a **positive** sign, the opposite of the causal hypothesis (nautical
products are discretionary purchases expected to be *suppressed* by higher
borrowing costs). An implausibly large effect with the wrong sign is the
signature of a confound: `PanelOLS(entity_effects=True)` only absorbs each
entity's own average level, with nothing representing this project's own
documented finding that the business grows ~14–17%/year, smoothly, every year
(`03_granularity_baselines`). SELIC and IPCA are the first features in the
entire chain that drift gradually across years rather than repeating
cyclically within a year — exactly the shape that spuriously picks up
a multi-year growth trend instead of (or in addition to) any genuine
economic relationship.

**The control** is a single continuous linear `trend` column (weeks since the
panel's start), a structural control present in every task's formula from 2.2
onward — not a per-year or per-week fixed effect, which would fully saturate the
time dimension and make every other time-varying feature (calendar, holidays,
weather, economic) unidentifiable. A single linear term also has the right shape
given the growth is smooth and consistent, not lumpy or year-specific.

**The two specifications side by side:**

| Term | Without trend control | With trend control (specification used) |
|---|---|---|
| `selic_rate` coefficient | +0.00266 | **−0.00040** |
| `selic_rate` t-stat / p-value | t = 38.1, p < 0.001 | t = −3.37, **p = 0.0007** |
| `ipca_monthly_variation` coefficient | +0.0034 | +0.0012 |
| `ipca_monthly_variation` p-value | p < 0.001 | **p = 0.115 — not significant** |
| `trend` coefficient | (absent) | +0.000230/week, t = 31.7, p < 0.001 |

**This is a direct confirmation of the confound diagnosis.**
`selic_rate`'s coefficient collapses by ~85% in magnitude and **takes the
theoretically expected negative sign** (higher interest rates *suppress* demand,
matching the discretionary-spending hypothesis) once the
model has somewhere else to put the shared multi-year trend. `ipca_monthly_variation`
is not significant with the control — its apparent effect without it is essentially
all trend.

## Results

| Metric | `baseline+calendar+holidays+weather` (+trend) | `+economic` (+trend) | % change |
|---|---|---|---|
| RMSE | 1.71200 | 1.71187 | −0.0076% |
| Bias | 0.28192 | 0.28122 | −0.25% |
| MAPE | 0.95965 | 0.95943 | **−0.023%** |
| sMAPE | 1.98931 | 1.98928 | −0.0015% |

**MAPE improvement vs. the previous formula: 0.023%** (0.48% without the trend
control, which would make economic indicators the largest single-task improvement in
the chain). **Threshold: >2% improvement. Does not meet the threshold, by a wide
margin.**

## Discussion

The accuracy story changes as much as the significance story: without the trend
control, economic indicators look like the strongest candidate feature group in the
chain (0.48% MAPE improvement, the closest to the 2% threshold of any task) largely
*because* they absorb the trend that no other feature has enough multi-year drift to
pick up. With the trend separated out, economic indicators' incremental contribution to
accuracy is close to zero (0.023%) — smaller than calendar's (0.60%, see
`02_calendar_report.md`) and comparable to holidays' and weather's negligible
contributions.

`selic_rate` being significant, small, and *correctly signed* with the trend control is
the one genuinely interesting result of this task: unlike `ipca_monthly_variation` (whose
effect fully evaporates), SELIC's trajectory over 2020–2025 was not monotonic (record
lows in 2020–2021, a sharp spike to ~13.75% in 2022–2023, then a gradual decline), so
there is real variation left after removing a straight-line trend for SELIC to explain —
and what is left points the theoretically expected direction. This is worth keeping in
the narrative as a small, credible, if practically minor, economic effect — a different
conclusion from "economic indicators don't matter," even though neither term clears the
accuracy bar.

## Recommendation — Checkpoint

**Not kept on accuracy grounds** (0.023% MAPE improvement, well short of 2%). The 0.48%
near-miss without the trend control is a trend artifact, not a closer call that falls
just short.

**`selic_rate`'s coefficient (small, significant, correctly signed) is worth preserving
in the client narrative** as a credible secondary finding, distinct from the headline
accuracy verdict — interest rates plausibly have a small, real dampening effect on this
discretionary category, even though it is not large enough to move forecast accuracy.
`ipca_monthly_variation` has no such residual credibility; its entire apparent effect is
the trend.

**Carried forward into the cumulative formula for task 2.6** under the
conservative-default policy (no confound identified between economic
indicators and marketing/discount timing). The task 2.10 ablation drops the economic
layer (`10_frozen_feature_set.md`).
