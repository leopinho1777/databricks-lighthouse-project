# Weather Feature Report — Stage 2 Feature Engineering (Task 2.4)

> Builds on task 2.3's `baseline+calendar+holidays` formula. MLflow run
> `baseline+calendar+holidays+weather` (`b133f4785d8743a281f99486022551e8`)
> logged under `/Shared/01_feature_iteration`; `baseline+calendar+holidays`
> is refit in-memory only, to compute this task's delta on the same code
> path — not re-logged, since task 2.3 already logs it.
>
> **Specification.** Every run includes a linear time-trend term as a permanent structural
> control (see `05_economic/05_economic_report.md`: without it, SELIC/IPCA's apparent
> effect is mostly a confound with this project's growth trend). The trend control changes
> this task's substantive result: with it `temp_mean` is negative and non-significant,
> `wind_max` is borderline significant, and the holiday terms (retested here as part of the
> cumulative formula) are non-significant. Results are reported with the control and, as a
> sensitivity check, without it.

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
- **Location proxy**: weather is joined through a 4-row
  `state_code → state-capital coordinates` table (`state_capital_coordinates.py`), via
  `dim_locations.state_code`, rather than through a per-city lookup.
  `dim_locations.city_name` is Faker-generated mock data (e.g. "Barbosa do Sul",
  "Cavalcanti da Mata" are not real, geocodable Brazilian cities — consistent with root
  `CLAUDE.md`'s note that this is a learning-only mock database), so geocoding cities would
  geocode fictional places. `state_code` values are real Brazilian states (PR, AP, PI, AL —
  4 distinct states across the 6 locations). This is a reasonable regional proxy, not a
  location-precise one.
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
threshold — with or without the trend control, though the
significance picture underneath differs substantially.**

**Coefficients (`output/coefficients.csv`) — the trend control changes the
substantive finding here, not just the numbers:**
- `temp_mean`: coefficient **−0.00022**, **p = 0.211 — not significant**
  (without the trend control: +0.0010, significant).
- `wind_max`: coefficient **+0.00016**, **p = 0.046 — borderline significant** at the
  conventional 0.05 level (without the control: +0.00043, clearly significant).
- `precip_sum`: not significant (p = 0.237; p = 0.998 without the control — nowhere
  near significant either way).
- `has_holiday`/`is_long_weekend` (retested here as part of the cumulative
  formula): also not significant (p = 0.281, p = 0.082), consistent with
  task 2.3's finding.

Month/week-of-year coefficients from task 2.2 are essentially unchanged
(compare against `02_calendar/output/coefficients.csv`), confirming — as in
task 2.3 — that calendar itself is not confounded with trend; only the
smaller, already-marginal weather and holiday terms are sensitive to it.

## Discussion

**Without the trend control two of the three weather terms are significant; that finding
does not survive the control.** Without it, `temp_mean` and `wind_max` are both
significant, with `temp_mean` positive. With the trend term, `temp_mean` is negative
(warmer weeks *suppressing* demand does not fit the boating hypothesis either, so this is
not a clean win, just a different sign) and non-significant, and `wind_max` survives only
at the margin (p = 0.046).

**`wind_max`'s counter-intuitive positive sign and marginal significance are not explained
by collinearity or by the trend control.** Task 2.9's VIF check finds `wind_max`'s VIF at
1.17–1.19 in both the calendar-only and full-formula (including `trend`) scopes, nowhere
near collinear. `temp_mean`'s coefficient does shift materially when trend is added, but a
low VIF means that shift is not explained by severe multicollinearity (VIF near 1–2 still
permits real, non-severe correlation, which can move a point estimate without being
"collinear" in the diagnostic sense): it is a real, modest omitted-variable effect, not
evidence the two terms are redundant. See
`09_multicollinearity_check/09_multicollinearity_report.md` for the full account; it is
the reference for this question in `10_frozen_feature_set.md`.

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

**Not kept** — weather does not clear the >2% MAPE-improvement bar (net change ≈ 0%),
and with the trend control in place none of its three terms is comfortably significant
(`temp_mean` p = 0.211, `precip_sum` p = 0.237, `wind_max` p = 0.046 borderline). The trend
control accounts for most of what looks like a weather effect without it; the residual
marginal `wind_max` effect is unexplained (task 2.9).

**Carried forward into the cumulative formula for task 2.5** under the
conservative-default policy (see Discussion). Its inclusion in the final production feature
set is decided by the task 2.10 ablation, which drops weather (removing the weather terms
slightly improves MAPE, −0.0161%; `10_frozen_feature_set.md`).
