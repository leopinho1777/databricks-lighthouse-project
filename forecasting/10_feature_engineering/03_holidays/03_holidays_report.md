# Holiday Feature Report — Stage 2 Feature Engineering (Task 2.3)

> Builds on task 2.2's `baseline+calendar` formula. MLflow run
> `baseline+calendar+holidays` (`d49d0b06ed0f468691d67c2130492cc1`) logged
> under `/Shared/01_feature_iteration`; `baseline+calendar` is refit
> in-memory only, to compute this task's delta on the same code path — not
> re-logged, since task 2.2 already logs it.
>
> **Specification.** Every run includes a linear time-trend term as a permanent structural
> control in `fit_and_evaluate()` (see `05_economic/05_economic_report.md`: without it,
> SELIC/IPCA's apparent effect is mostly a confound with this project's growth trend).
> The trend control changes the substantive holiday result below — `has_holiday` and
> `is_long_weekend` are both non-significant with it — so the results are reported with
> the control and, as a sensitivity check, without it.

## Method

- Same panel/estimator/train-holdout split as task 2.2
  (`PanelOLS(entity_effects=True)`, entity = `(product_variant_id,
  location_id)`, train 2020–2024, holdout 2025).
- `add_calendar_features()` imported directly from
  `02_calendar/add_calendar_features.py` rather than reimplemented — this
  chain is explicitly cumulative by design, so each task extends the exact
  prior formula rather than each stage duplicating shared logic (contrast
  with `forecasting/03`-`09`, which are independent one-off analyses).
- New features: `has_holiday` (week contains ≥1 Brazilian holiday) and
  `is_long_weekend` (week contains a holiday on Mon/Tue/Thu/Fri, adjacent to
  the weekend). Uses the `holidays` package's Brazil calendar with **both**
  `public` (statutory) and `optional` categories — `public` alone excludes
  Carnival entirely, which is central to this feature's own causal hypothesis
  in `00_feature_backlog.md` (Carnival is a major driver of Brazilian
  beach/boating tourism). National-level holidays only, no state/municipal
  subdivisions.

## Results

| Metric | `baseline+calendar` (+trend) | `baseline+calendar+holidays` (+trend) | % change |
|---|---|---|---|
| RMSE | 1.71189 | 1.71191 | +0.0014% |
| Bias | 0.28125 | 0.28141 | +0.055% |
| MAPE | 0.95945 | 0.95950 | +0.0046% |
| sMAPE | 1.98929 | 1.98930 | +0.0006% |

**MAPE change vs. `baseline+calendar`: essentially zero (+0.005%, marginally
worse). Threshold: >2% improvement. Does not meet the threshold — not even
directionally close, with or without the trend control.**

**Coefficients (`output/coefficients.csv`) — this is where the trend control
changes the substantive finding, not just the numbers:**
- `has_holiday`: coefficient **+0.0018**, **p = 0.235 — not significant**
  (without the trend control: +0.0061, p < 0.001).
- `is_long_weekend`: coefficient **−0.0028**, **p = 0.070 — not significant at
  the conventional 0.05 level** (without the control: −0.0090, p < 0.001).
- With the control both coefficients are roughly one-third of their size without it,
  not just less significant.

Month/week-of-year coefficients from task 2.2 are essentially unchanged
here (compare `output/coefficients.csv` against `02_calendar/output/coefficients.csv`),
so calendar itself is not confounded with trend — only the much smaller,
already-marginal holiday effects are sensitive to it.

## Discussion

**Without the trend control the two holiday terms are both significant and
opposite-signed, which reads as "roughly cancel out"; that finding does not survive the
control.** Calendar and holidays could be expected to be unaffected, since they are
cyclical variables with no multi-year drift of their own, unlike SELIC/IPCA. That holds
for calendar (see `02_calendar_report.md` — month coefficients unchanged) but **not fully
for holidays**: both terms lose significance once trend is added. The likely mechanism is
different from SELIC's: holidays are not drifting over time themselves, but with only 5
training years and ~16 fixed holiday dates per year, some of what the model without a
trend attributes to "is this a holiday week" may be where those specific weeks fall
relative to the business's overall growth curve across the 5 years, not a real recurring
holiday effect. This is a more modest, subtler version of the confound found in task 2.5
(see there), and it makes this task's verdict **"no significant effect can be established
once trend is controlled"** — a clean negative result.

This is a genuine negative result on both the accuracy question and the significance
question, not a coding issue: it is entirely plausible that
holidays and long weekends have real effects on Brazilian nautical retail
that this specific weekly, national-holiday-only formulation simply cannot
detect at this data volume (only 5 training years, ~16 holiday dates/year).
That absence of evidence is not evidence of absence, but it does mean
neither the accuracy nor the significance signal supports keeping this
feature as currently specified.

**Caveat: a catalog-wide non-significant result describes the whole-catalog
average, not a claim that holidays have zero differential effect anywhere in
the catalog.** The pooled panel regression estimates a single
population-level coefficient per feature by construction, so it cannot see
whether, say, long-weekend suppression hits products bought for immediate
use harder than stockpiled items, or whether the effect differs by the
demand-pattern segments found in `04_demand_classification` (Intermittent
vs. Lumpy). A catalog-wide null result is consistent with genuinely
negligible effects everywhere, but is equally consistent with real,
offsetting effects at the segment level that happen to net out in aggregate.
Worth revisiting if/when segment-level results get cross-referenced later —
not a blocker for this task's verdict or for proceeding to 2.4.

**On carrying holidays forward into task 2.4 (weather) regardless of this
result**: per the Stage 2 plan and task methodology,
tasks 2.2–2.7 are cumulative by design — each task tests its own marginal
contribution against the *full* accumulated formula so far, independent of
whether every earlier layer individually cleared its own threshold. This is
the same principle task 2.2's checkpoint clarified for calendar (retained as
a control to prevent omitted-variable bias in later coefficients), and it
applies generally here too, not just as a one-off exception: dropping
holidays before testing weather could still misattribute some of the
already-tiny observed holiday effect to weather if the two happen to
co-occur (e.g. Carnival falling in a particular weather regime), so holidays
stay in the base formula for 2.4 onward.

## Recommendation — Checkpoint

**Not kept** — holidays/long-weekend flags do not clear the >2%
MAPE-improvement bar (net change ≈ 0%), and with the trend control in
place neither coefficient is statistically significant either (see Discussion for
why the result without the control does not hold up). Logged with the same rigor as
task 2.2's.

**Carried forward into the cumulative formula for task 2.4** per the
project's cumulative-testing design (see Discussion). Its inclusion in the
final production feature set is decided separately by the task 2.10 ablation, which
drops holidays (removing the holiday terms slightly improves MAPE, −0.0038%;
`10_frozen_feature_set.md`).
