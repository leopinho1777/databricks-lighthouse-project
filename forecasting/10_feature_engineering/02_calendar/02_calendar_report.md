# Calendar & Seasonality Feature Report — Stage 2 Feature Engineering (Task 2.2)

> **Specification.** The verdict is measured against a zero-feature reference run
> (`entity_fe_only`), as the >2% MAPE-improvement threshold requires. Every run includes
> a linear time-trend term as a permanent structural control in
> `_shared/panel_regression.py`'s `fit_and_evaluate()` (see
> `05_economic/05_economic_report.md` for why: without it, SELIC/IPCA's apparent effect is
> almost entirely a confound with this project's ~15%/year growth trend). `trend` is **not**
> a candidate feature — it gets no keep/drop verdict, no causal-hypothesis row, and is not
> part of the cumulative-retention policy discussion below; it makes every other
> coefficient interpretable. See `00_feature_backlog.md`'s dedicated section.
>
> MLflow runs: `entity_fe_only` (`db6f7894ef324137a5200d605de70d00`) and
> `baseline+calendar` (`a54f9e69adb24445b863922236285e2a`), both under
> `/Shared/01_feature_iteration`.

## Method

- Panel: `fact_demand_daily` (each developer's own scratch copy — see
  `../../README.md`'s "Data source convention") rolled up to
  product×location×ISO-week (6,054 entities, 262 weeks), target
  `log1p(qty_sold_net)`.
- Estimator: `linearmodels.PanelOLS(entity_effects=True)`, entity = the
  `(product_variant_id, location_id)` pair, clustered SEs by entity.
- Train: 2020–2024 (`most_recent_complete_year()` = 2025). Holdout: 2025,
  metrics back-transformed via `expm1()` and computed on raw `qty_sold_net`.
- **Reference run** (`entity_fe_only`): zero features — each entity's own
  training-period mean `log_qty` carried flat into every holdout week (i.e.
  entity fixed effects only). This is the mandatory "previous run" task 2.2's
  delta is measured against, since 2.2 is the first cumulative feature task
  and there is no earlier task in the chain to diff against.
- **Calendar run** (`baseline+calendar`): month dummies (`month_2`…`month_12`,
  January is the reference category) + `week_of_year_sin`/`week_of_year_cos`.
  Day-of-week/`is_weekend` were dropped (not meaningful at weekly grain);
  quarter was dropped (perfectly collinear with the month dummies as a set).
- **Both runs include `trend`** (weeks elapsed since the panel's first period), a
  structural control in `fit_and_evaluate()` — present in every run regardless of
  `feature_cols`, not something this task chooses.

## Results

| Metric | `entity_fe_only` (+trend) | `baseline+calendar` (+trend) | % change |
|---|---|---|---|
| RMSE | 1.7160 | 1.7119 | −0.24% |
| Bias | 0.2857 | 0.2813 | −1.54% |
| MAPE | 0.9652 | 0.9595 | **−0.60%** |
| sMAPE | 1.9907 | 1.9893 | −0.07% |

**MAPE improvement vs. the entity-fixed-effects-plus-trend reference: 0.60%
(0.46% if the trend control is left out of both runs — the trend gives the reference
itself a better baseline to improve on, but the picture is the same).
Threshold: >2%. Does not meet the threshold.**

Coefficient significance (`output/coefficients.csv`), with the trend control in place:
- All 11 month dummies are significant at p < 0.001, tracing a clean, monotonic
  within-year curve (smallest negative coefficient in December/January,
  Southern-hemisphere summer; largest negative in June–August, Southern winter). They
  are **not** confounded with the trend, unlike some of task 2.3/2.4's terms (see
  those reports).
- `week_of_year_cos` is significant (p < 0.001); `week_of_year_sin` is not
  significant (p = 0.13).
- `trend` itself: **+0.000211/week, t = 50.3, p < 0.001** — confirms the
  project's known multi-year growth trend is real and substantial in this
  panel too, exactly the effect this control exists to separate from every
  other feature's coefficient.

## Discussion

**Statistical significance and accuracy improvement answer different
questions here, and they disagree.** With ~1.58M training observations, the
panel regression has enough power to detect month-level effects as
significant even though their magnitude (coefficients of roughly −0.01 to
−0.06 in log1p space, i.e. single-digit-percent shifts in expected quantity)
is small relative to the total forecast error at the individual
product×location×week grain — a grain that is 92.9%-zero and dominated by
cross-entity variance the fixed effect already absorbs, and by idiosyncratic
week-to-week noise neither run's formula touches. The month effects are real
and explainable (useful for the client narrative), but they are not large
enough, on their own, to move the accuracy needle past the 2%-MAPE-improvement
bar this project uses to decide what earns a place in the final model.

**Calendar is retained as a control variable, not as a kept
feature — these are two different roles.** Brazilian holidays cluster in
specific months (Carnival in Feb/Mar, Christmas/New Year in Dec/Jan), which
overlaps directly with the Nov–Jan boating-season peak this task's own month
coefficients already found. If task 2.3 tested holidays against
`entity_fe_only` (dropping calendar first), the holiday coefficient would
have no month term to control against and would likely absorb part of the
general seasonal effect — a standard omitted-variable-bias risk in
stepwise/hierarchical regression. So calendar stays in the cumulative formula
specifically to prevent later features (holidays, weather) from
misattributing seasonal variance to themselves, independent of whether
calendar earns a permanent place in the final production feature set.

## Recommendation — Checkpoint

**Per-task accuracy verdict: not kept as a standalone feature** — calendar/
seasonality alone does not clear the >2% MAPE-improvement bar against the
trend-controlled zero-feature reference (0.60% improvement), despite
statistically significant, theoretically consistent coefficients that are unchanged by
the trend control. This is recorded as a genuine negative result, not a partial
positive one.

**Retained as a seasonal control variable** in the cumulative formula tasks
2.3–2.7 build on, to prevent omitted-variable bias in later features'
coefficients (see Discussion above) — this is a different justification than
"kept," and should not be conflated with it in `10_frozen_feature_set.md`.

**Ablation in task 2.10.** Because calendar's role in the chain is bias prevention, the
final assembled formula is also fit with and without the calendar terms
(`../run_ablation.py`). Removing calendar makes MAPE worse by 0.44%, 19–280× the effect of
any other layer, so calendar's month dummies earn a place in the production feature set on
accuracy grounds. The distinction between control-for-bias-prevention and
earned-its-place-on-accuracy is stated in `10_frozen_feature_set.md`.
