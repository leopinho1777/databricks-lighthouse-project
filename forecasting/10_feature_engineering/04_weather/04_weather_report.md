# Weather Feature Report — Stage 2 Feature Engineering (Task 2.4)

> Builds on task 2.3's `baseline+calendar+holidays` formula. MLflow run
> `baseline+calendar+holidays+weather` (`b133f4785d8743a281f99486022551e8`)
> logged under `/Shared/01_feature_iteration`; `baseline+calendar+holidays`
> was refit in-memory only, to compute this task's delta on the same code
> path — not re-logged, since task 2.3 already logged it.
>
> Re-run twice since the original version: a holiday year-range edge-case fix
> (see `03_holidays/03_holidays_report.md`'s note — did not change this
> task's substantive result), then **a linear time-trend term added as a
> permanent structural control** after task 2.5 found SELIC/IPCA's apparent
> effect was mostly a confound with this project's known growth trend (see
> `05_economic/05_economic_report.md`). **The trend control changed this
> task's substantive result**: `temp_mean` flips sign and loses
> significance, `wind_max` shrinks to borderline significance, and the
> holiday terms (retested here as part of the cumulative formula) also lose
> significance — this was checked, not assumed, and the result is reported
> as found.

## Method

- Same panel/estimator/train-holdout split as tasks 2.2–2.3
  (`PanelOLS(entity_effects=True)`, entity = `(product_variant_id,
  location_id)`, train 2020–2024, holdout 2025).
- `add_calendar_features()` and `add_holiday_features()` imported directly
  from `02_calendar/` and `03_holidays/` respectively, extending the same
  cumulative chain.
- **Weather data doesn't exist anywhere in this project** (confirmed during
  exploration before this stage started). Sourced from Open-Meteo's free
  historical archive API (no key required), no committed dbt model changes.
- **Location proxy — deviation from the original plan, with reason**: the
  plan called for a 6-row `location_id → (lat, lon)` lookup, one per
  location. `dim_locations.city_name` turned out to be Faker-generated mock
  data (e.g. "Barbosa do Sul", "Cavalcanti da Mata" aren't real, geocodable
  Brazilian cities — consistent with root `CLAUDE.md`'s note that this is a
  learning-only mock database), so a per-city lookup would have been
  geocoding fictional places. `state_code` values ARE real Brazilian states
  (PR, AP, PI, AL — 4 distinct states across the 6 locations), so the lookup
  used instead is a 4-row `state_code → state-capital coordinates` table
  (`state_capital_coordinates.py`), joined via `dim_locations.state_code`.
  This is a reasonable regional proxy, not a location-precise one.
- Features: `temp_mean` (weekly mean of daily mean temperature, °C),
  `precip_sum` (weekly total precipitation, mm), `wind_max` (weekly max of
  daily max wind speed, km/h) — daily Open-Meteo values aggregated to
  ISO-week per state, then broadcast to every location in that state.

## Results

| Metric | `baseline+calendar+holidays` (+trend) | `+weather` (+trend) | % change |
|---|---|---|---|
| RMSE | 1.71191 | 1.71200 | +0.0053% |
| Bias | 0.28141 | 0.28192 | +0.18% |
| MAPE | 0.95950 | 0.95965 | +0.016% |
| sMAPE | 1.98930 | 1.98931 | +0.0006% |

**MAPE change vs. `baseline+calendar+holidays`: essentially zero (+0.016%,
marginally worse). Threshold: >2% improvement. Does not meet the
threshold — same conclusion as before the trend control, though the
significance picture underneath changed substantially.**

**Coefficients (`output/coefficients.csv`) — the trend control changed the
substantive finding here, not just the numbers:**
- `temp_mean`: coefficient **flips to −0.00022** (was +0.0010), **p = 0.211
  — no longer significant.**
- `wind_max`: coefficient shrinks to **+0.00016** (was +0.00043), **p =
  0.046 — now only borderline significant** at the conventional 0.05 level.
- `precip_sum`: still not significant (p = 0.237, was p = 0.998 — moved, but
  nowhere near significant either way).
- `has_holiday`/`is_long_weekend` (retested here as part of the cumulative
  formula): also not significant (p = 0.281, p = 0.082), consistent with
  task 2.3's corrected finding.

Month/week-of-year coefficients from task 2.2 remain essentially unchanged
(compare against `02_calendar/output/coefficients.csv`), confirming — as in
task 2.3 — that calendar itself wasn't confounded with trend; only the
smaller, already-marginal weather and holiday terms were sensitive to it.

## Discussion

**The original "two of three weather terms are significant" finding does
not survive the trend control, and — as with task 2.3's holidays — this was
not assumed to hold, it was checked.** Before the trend control, `temp_mean`
and `wind_max` were both significant with `temp_mean` positive; after
adding trend, `temp_mean` flips negative (the theoretically expected
direction — warmer weeks *suppressing* demand doesn't fit the boating
hypothesis either, so this isn't a clean win, just a different sign) and
loses significance entirely, and `wind_max` survives only at the margin
(p = 0.046).
>
> **Correction (after task 2.9 ran):** this section originally claimed the
> trend control had "resolved the puzzle," implying `wind_max`'s
> counter-intuitive sign was explained away by collinearity with calendar
> or trend. **Task 2.9's VIF check found the opposite** — `wind_max`'s VIF
> is 1.17–1.19 in both the calendar-only and full-formula (including
> `trend`) scopes, nowhere near collinear. `temp_mean`'s coefficient *did*
> shift materially when trend was added, but a low VIF means that shift
> isn't explained by severe multicollinearity (VIF near 1–2 still permits
> real, non-severe correlation, which can legitimately move a point
> estimate without being "collinear" in the diagnostic sense) — it's a
> real, modest omitted-variable correction, not evidence the two terms were
> redundant. **`wind_max`'s counter-intuitive sign and marginal
> significance remain unexplained by either the trend control or task 2.9's
> collinearity check** — see `09_multicollinearity_check/09_multicollinearity_report.md`
> for the full, corrected account. This report's own earlier claim should
> not be relied on in `10_frozen_feature_set.md`; task 2.9's is the current
> word on this question.

`precip_sum` remains non-significant under both specifications — the
cleanest, most stable negative sub-finding in this task: rainfall does not
measurably move weekly demand for this catalog, with or without a trend
control.

**Carrying weather forward into task 2.5 (economic)**: per the
`00_feature_backlog.md` standing rule (as refined after task 2.3's
checkpoint), this needs its own stated justification, not an inherited one.
No specific confound mechanism between weekly weather and national-level
macroeconomic indicators (SELIC, IPCA) has been identified — they move on
unrelated timescales and drivers. Weather is therefore retained in the chain
under the **conservative-default** justification (cost-effectiveness of not
re-deriving confound-freeness at every step), not because omitted-variable
bias was demonstrated the way it was for calendar→holidays.

## Recommendation — Checkpoint

**Not kept, and more clearly so than the original version of this report**
— weather does not clear the >2% MAPE-improvement bar (net change ≈ 0%),
and once the trend control is in place none of its three terms is
comfortably significant (`temp_mean` p = 0.211, `precip_sum` p = 0.237,
`wind_max` p = 0.046 borderline). The pre-trend-control version of this
report treated `temp_mean`/`wind_max` as real effects worth further VIF
investigation in task 2.9 — that framing no longer applies; the trend
control already explains most of what looked like a weather effect.

**Carried forward into the cumulative formula for task 2.5** under the
conservative-default policy (see Discussion) — its inclusion in the final
production feature set (task 2.10) remains open, though with the
significance picture this weak, it is unlikely to survive 2.10's ablation.

**Stopping here per the checkpoint constraint in the approved plan.**
