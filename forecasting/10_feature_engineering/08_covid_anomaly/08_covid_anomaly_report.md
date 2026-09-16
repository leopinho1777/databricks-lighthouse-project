# COVID Anomaly Investigation — Stage 2 Feature Engineering (Task 2.8)

> Independent of the cumulative feature chain (2.2–2.7). Produces a written
> recommendation for the team on how 2020–2021 should be treated in
> training — not a unilateral change to the training window used by any
> task in this stage or by Stage 3.

## Starting point: Phase 1 already checked this

`01_data_exploration_summary.md` section 3 ran this exact question at the
portfolio-revenue level and concluded: **no 2020–2021 anomaly** — annual
revenue growth is smooth and monotonic (+14.0% to +17.1% every year,
including 2020→2021), consistent with this being mock/synthetic data that
doesn't encode the real-world COVID disruption the business risk
description anticipated. This task doesn't re-litigate that from scratch —
it reconciles it on a different metric and adds a model-based check Phase
1's raw-totals comparison couldn't provide.

## Check 1 — portfolio-total `qty_sold_net` by year (reconciles Phase 1 on quantity, not revenue)

| Year | qty_sold_net | YoY % |
|---|---|---|
| 2020 | 63,639 | — |
| 2021 | 72,297 | +13.6% |
| 2022 | 83,230 | +15.1% |
| 2023 | 94,979 | +14.1% |
| 2024 | 111,670 | +17.6% |
| 2025 | 127,966 | +14.6% |
| 2026* | 90,086 | −29.6% (partial year, not comparable) |

(`output/yearly_totals.csv`, `output/yearly_totals.png`. The panel's first
period-week is a stray partial week labeled year 2019 by ISO-week
convention — dropped here, it produced a meaningless "+4586%" artifact
against a near-empty prior-year base.)

**2020→2021 growth (+13.6%) sits inside the same +14–18% band as every
other year.** This matches Phase 1's revenue-based numbers closely and
confirms the finding independently on the quantity metric this stage's
panel is actually built on.

## Check 2 — monthly seasonal shape overlay (new: shape, not just level)

`output/monthly_shape_by_year.png` overlays every year's monthly total
(2020–2021 dashed). Every year traces the same seasonal curve — peak
Dec–Mar (Southern-hemisphere summer), trough Jun–Jul — including 2020 and
2021, which sit uniformly lower only because the whole business was smaller
then (consistent with the steady growth trend, not a demand-shape
disruption). There is no visible shift in *when* the peak/trough falls, no
flattened or distorted curve in 2020/2021 relative to later years. Phase
1's annual-total and Jan–Aug comparisons couldn't show this directly; this
chart is the complementary check that confirms the *shape*, not just the
*level*, is unaffected.

## Check 3 — residual check from an already-fitted model (new: controls for seasonality/entity level)

Using task 2.2's already-fitted `baseline+calendar` `PanelOLS` model (entity
fixed effects + month/week-of-year seasonality, trained on 2020–2024), mean
residual (in log1p space) by year:

| Year | Mean residual | Std | n |
|---|---|---|---|
| 2020 | +0.0021 | 0.343 | 314,808 |
| 2021 | −0.0006 | 0.364 | 314,808 |
| 2022 | −0.0014 | 0.388 | 314,808 |
| 2023 | −0.0009 | 0.413 | 314,808 |
| 2024 | +0.0014 | 0.442 | 320,862 |

(2019's stray single week, mean −0.0285 on 6,054 rows, omitted from this
comparison as the same artifact noted above.)

**All five years' mean residuals are within ±0.002 of zero — 2020 and 2021
are not distinguishable from 2022–2024.** If 2020–2021 had been
systematically over- or under-predicted once seasonality and each series'
own baseline level are controlled for, that would show up here as a
residual mean well away from zero relative to the other years; it doesn't.
This is a different, model-based lens from checks 1–2 (it asks "does the
calendar+entity-FE model's own error pattern single out these years,"
not just "does the raw total look different") and it corroborates the same
conclusion.

## Recommendation

**Flag, don't exclude or down-weight.** Three independent checks — Phase
1's original revenue-based annual comparison, this task's quantity-based
reconciliation with a monthly shape overlay, and a residual check from an
already-fitted seasonal model — all agree: **2020–2021 shows no detectable
anomaly in this dataset**, in level, in shape, or in model residuals. This
is consistent with the dataset being synthetic/mock data that was not
designed to encode the real-world COVID disruption.

Given that, there is nothing to correct for, and no basis for excluding or
down-weighting 2020–2021 in training — doing so would remove two years of
otherwise-normal training data for no benefit. This recommendation is
presented to the team for confirmation, not applied unilaterally: if the
team has out-of-band knowledge that 2020–2021 should be treated specially
regardless of what this dataset shows (e.g., anticipating that a future,
less-synthetic data refresh will need this handling), that's a decision for
them, not something this check can resolve on its own.

**No change to any task's training window** as a result of this task —
2020–2024 remains the training period, 2025 the holdout, throughout Stage 2.

**Stopping here — task 2.8 is independent of the cumulative chain, so this
is not a checkpoint gating task 2.9, but is reported the same way.**
