# Economic Feature Report — Stage 2 Feature Engineering (Task 2.5)

> **This report supersedes its original version, which flagged (but did not
> resolve) a suspected trend confound.** A linear time-trend term has since
> been added as a permanent structural control to
> `_shared/panel_regression.py`'s `fit_and_evaluate()`, applied retroactively
> to tasks 2.2–2.5 (see `00_feature_backlog.md`'s dedicated section on this
> control). This report presents the trend-controlled result, which
> **confirms the confound diagnosis directly**: SELIC's coefficient shrinks
> by ~85% and flips to the theoretically-expected sign once trend is
> present. MLflow run `baseline+calendar+holidays+weather+economic`
> (`374d3a760208437899320a950df3e3c0`) logged under
> `/Shared/01_feature_iteration`; the previous formula was refit in-memory
> only, to compute this task's delta — not re-logged, since task 2.4 already
> logged it.

## Method

- Same panel/estimator/train-holdout split as tasks 2.2–2.4
  (`PanelOLS(entity_effects=True)`, entity = `(product_variant_id,
  location_id)`, train 2020–2024, holdout 2025), now with a linear `trend`
  term (weeks elapsed since the panel's first period) added as a permanent
  structural control in every run, per the fix described below.
- `add_calendar_features()`, `add_holiday_features()`, `add_weather_features()`
  imported directly from their respective task folders, extending the same
  cumulative chain.
- Economic data sourced from BCB's free SGS API (Banco Central do Brasil),
  not the tracker's literal FRED (US) suggestion, per the team decision made
  before this stage started. Series: **SELIC** (series 432, daily target
  interest rate, % a.a., aggregated to weekly mean) and **IPCA** (series
  433, monthly inflation variation, % — forward-filled to every week within
  its publication month). Both national-level, no location join needed.

## The confound, and how it was found and resolved

**Before the trend control**, `selic_rate` showed a coefficient of **+0.00266**
with **t = 38.1** — by far the most extreme result anywhere in this chain
(every other feature's t-stat was in the single-to-low-double digits) — and
a **positive** sign, the opposite of the causal hypothesis (nautical
products are discretionary purchases expected to be *suppressed* by higher
borrowing costs). That combination — an implausibly large effect with the
wrong sign — was flagged as very likely a confound rather than a genuine
finding: `PanelOLS(entity_effects=True)` only absorbs each entity's own
average level, with nothing representing this project's own documented
finding that the business grows ~14–17%/year, smoothly, every year
(`03_granularity_baselines`). SELIC and IPCA were the first features in the
entire chain that drift gradually across years rather than repeating
cyclically within a year — exactly the shape that would spuriously pick up
a multi-year growth trend instead of (or in addition to) any genuine
economic relationship.

**The fix**: a single continuous linear `trend` column (weeks since the
panel's start), added to `fit_and_evaluate()` as a structural control
present in every task's formula from 2.2 forward — not a per-year or
per-week fixed effect, which would have fully saturated the time dimension
and made every other time-varying feature (calendar, holidays, weather,
economic) unidentifiable. A single linear term is also the correctly-shaped
control given the growth was already found to be smooth and consistent, not
lumpy or year-specific.

**The result, re-fit with trend present:**

| Term | Before trend control | After trend control |
|---|---|---|
| `selic_rate` coefficient | +0.00266 | **−0.00040** |
| `selic_rate` t-stat / p-value | t = 38.1, p < 0.001 | t = −3.37, **p = 0.0007** |
| `ipca_monthly_variation` coefficient | +0.0034 | +0.0012 |
| `ipca_monthly_variation` p-value | p < 0.001 | **p = 0.115 — no longer significant** |
| `trend` coefficient | (absent) | +0.000230/week, t = 31.7, p < 0.001 |

**This is a direct, dramatic confirmation of the confound diagnosis.**
`selic_rate`'s coefficient collapsed by ~85% in magnitude and **flipped to
the theoretically expected negative sign** (higher interest rates now
*suppress* demand, matching the discretionary-spending hypothesis) once the
model has somewhere else to put the shared multi-year trend. `ipca_monthly_variation`
lost significance entirely — its apparent effect was essentially all trend.

## Results

| Metric | `baseline+calendar+holidays+weather` (+trend) | `+economic` (+trend) | % change |
|---|---|---|---|
| RMSE | 1.71200 | 1.71187 | −0.0076% |
| Bias | 0.28192 | 0.28122 | −0.25% |
| MAPE | 0.95965 | 0.95943 | **−0.023%** |
| sMAPE | 1.98931 | 1.98928 | −0.0015% |

**MAPE improvement vs. the previous formula: 0.023% — down from the 0.48%
reported before the trend control (which was, at the time, the largest
single-task improvement in the chain). Threshold: >2% improvement. Does not
meet the threshold, and by a much wider margin than it first appeared.**

## Discussion

The accuracy story changes as much as the significance story: economic
indicators looked like the strongest candidate feature group in the entire
chain (0.48% MAPE improvement, the closest to the 2% threshold of any task
so far) largely *because* they were silently absorbing the trend that no
other feature in the chain has enough multi-year drift to pick up. With
trend properly separated out, economic indicators' actual incremental
contribution to accuracy is close to zero (0.023%) — smaller than
calendar's post-trend contribution (0.60%, see `02_calendar_report.md`) and
comparable to holidays' and weather's negligible contributions.

`selic_rate` surviving as significant, small, and *correctly signed* after
the trend correction is the one genuinely interesting result to come out of
this task: unlike `ipca_monthly_variation` (whose effect fully evaporated),
SELIC's trajectory over 2020–2025 was not monotonic (record lows in
2020–2021, a sharp spike to ~13.75% in 2022–2023, then a gradual decline),
so there is real variation left after removing a straight-line trend for
SELIC to explain — and what's left points the theoretically expected
direction. This is worth keeping in the narrative as a small, credible,
if practically minor, economic effect — a genuinely different conclusion
from "economic indicators don't matter," even though neither term clears
the accuracy bar.

## Recommendation — Checkpoint

**Not kept on accuracy grounds** (0.023% MAPE improvement, well short of
2%), **and the earlier near-miss (0.48%) is now understood to have been
mostly a trend artifact, not a closer call that fell just short.** This is a
stronger, more precise negative result than the original version of this
report, not a weaker one.

**`selic_rate`'s post-correction coefficient (small, significant, correctly
signed) is worth preserving in the client narrative** as a credible
secondary finding, distinct from the headline accuracy verdict — interest
rates plausibly have a small, real dampening effect on this discretionary
category, even though it isn't large enough to move the forecast accuracy
needle. `ipca_monthly_variation` has no such residual credibility; its
entire apparent effect was the trend.

**Carried forward into the cumulative formula for task 2.6** under the
conservative-default policy (no confound identified between economic
indicators and marketing/discount timing).

**Stopping here per the checkpoint constraint in the approved plan.**
