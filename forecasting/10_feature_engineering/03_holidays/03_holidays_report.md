# Holiday Feature Report — Stage 2 Feature Engineering (Task 2.3)

> Builds on task 2.2's `baseline+calendar` formula. MLflow run
> `baseline+calendar+holidays` (`d49d0b06ed0f468691d67c2130492cc1`) logged
> under `/Shared/01_feature_iteration`; `baseline+calendar` was refit
> in-memory only, to compute this task's delta on the same code path — not
> re-logged, since task 2.2 already logged it.
>
> Re-run twice since the original version:
> 1. A small edge-case bug fix (holiday-year range missing a January 1st
>    holiday in the last ISO week of a year) — did not change this task's
>    own numbers, only a downstream inconsistency (see git history for
>    detail; superseded by the fix below anyway).
> 2. **A linear time-trend term was added as a permanent structural control**
>    to `fit_and_evaluate()` after task 2.5 found SELIC/IPCA's apparent
>    effect was mostly a confound with this project's known growth trend
>    (see `05_economic/05_economic_report.md`). Applied retroactively here.
>    **This changed the substantive result below** — `has_holiday` and
>    `is_long_weekend` both lose statistical significance once trend is
>    controlled. This was not assumed to hold and is reported as found, not
>    as expected.

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
directionally close, same conclusion as before the trend control.**

**Coefficients (`output/coefficients.csv`) — this is where the trend control
changed the substantive finding, not just the numbers:**
- `has_holiday`: coefficient **+0.0018**, **p = 0.235 — no longer
  significant** (was +0.0061, p < 0.001 before the trend control).
- `is_long_weekend`: coefficient **−0.0028**, **p = 0.070 — no longer
  significant at the conventional 0.05 level** (was −0.0090, p < 0.001
  before).
- Both coefficients also shrank in magnitude (roughly one-third of their
  original size), not just in significance.

Month/week-of-year coefficients from task 2.2 remain essentially unchanged
here (compare `output/coefficients.csv` against `02_calendar/output/coefficients.csv`),
so calendar itself wasn't confounded with trend — only the much smaller,
already-marginal holiday effects were sensitive to it.

## Discussion

**The original "both significant, opposite-signed, roughly cancel out"
finding does not survive the trend control, and this needed to be checked
rather than assumed.** When task 2.5 flagged the trend confound, calendar and
holidays were expected to "hold" on the reasoning that they're cyclical
variables with no multi-year drift of their own, unlike SELIC/IPCA. That
reasoning held for calendar (see `02_calendar_report.md` — month coefficients
unchanged) but **did not fully hold for holidays**: both terms lost
significance once trend was added. The likely mechanism is different from
SELIC's: holidays aren't drifting over time themselves, but with only 5
training years and ~16 fixed holiday dates per year, some of what the
pre-trend model attributed to "is this a holiday week" may have actually
been capturing where those specific weeks happened to fall relative to the
business's overall growth curve across the 5 years, not a real recurring
holiday effect. This is a more modest, subtler version of the same
confound risk, not the dramatic one found in task 2.5 (see there), but it
changes this task's honest verdict from "two small-but-real effects that
happen to cancel out" to **"no significant effect can be established once
trend is properly controlled" — a cleaner, more clearly negative result.

This is a genuine negative result on the accuracy question, and now also on
the significance question, not a coding issue: it is entirely plausible that
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
result**: per the approved Stage 2 plan and the original task methodology,
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
MAPE-improvement bar (net change ≈ 0%), and once the trend control is in
place, neither coefficient is statistically significant either (was both
significant, opposite-signed, before the fix — see Discussion for why that
result didn't hold up). A cleaner negative result than originally reported,
logged with the same rigor as task 2.2's.

**Carried forward into the cumulative formula for task 2.4** per the
project's cumulative-testing design (see Discussion) — its inclusion in the
final production feature set (task 2.10) is separately still open, same as
calendar's.

**Stopping here per the checkpoint constraint in the approved plan.**
