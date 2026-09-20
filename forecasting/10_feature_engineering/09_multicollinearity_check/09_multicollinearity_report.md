# Multicollinearity Report — Stage 2 Feature Engineering (Task 2.9)

> Answers the question task 2.4's report explicitly left open: is weather
> redundant with calendar (supporting "wind is tracking seasonal timing, not
> a real weather effect"), or not (leaving the counter-intuitive `wind_max`
> sign unexplained)? **Result: VIF comes back low. The sign is not explained
> by this check — reported plainly, not papered over with the
> seasonal-timing theory by default.**

## Method

- VIF computed on **entity-demeaned** regressors — the within-transform
  `PanelOLS(entity_effects=True)` actually fits on (each column minus its
  own entity's training-period mean), not the raw columns. Collinearity in
  the raw data isn't the same question as collinearity in the variation the
  fixed-effects estimator actually uses to identify coefficients.
- Two scopes, since the tracker's literal ask and this task's given
  instruction (task 2.6's formula) differ:
  1. **Calendar + weather only** — the tracker's literal scope.
  2. **Full task 2.6 cumulative formula** (+ `trend`) — weather's VIF against
     everything currently in the model.
- Threshold: VIF > 5 (the conservative end of the conventional 5–10 range —
  chosen to make the ridge fallback easier to trigger, not harder).
- **Data types**: `discount_rate` comes back from the Databricks SQL connector's
  `DECIMAL` columns as Python `Decimal` (object dtype), which raises a `TypeError` on direct
  pandas arithmetic such as the VIF computation (`linearmodels` coerces it internally in
  the regressions). `06_marketing/add_marketing_features.py` therefore casts it with
  an explicit `.astype("float64")` right after querying; the task 2.6 regression results
  are identical with or without the cast.

## Results

**Weather terms' VIF (both scopes):**

| Term | VIF (calendar + weather only) | VIF (full task 2.6 formula) |
|---|---|---|
| `temp_mean` | 1.49 | 1.55 |
| `precip_sum` | 1.45 | 1.46 |
| `wind_max` | **1.17** | **1.19** |

**All three weather terms have VIF close to 1 (no correlation) in both
scopes — nowhere near the 5.0 threshold, let alone the top of the
conventional 5–10 range.** The ridge fallback was not triggered and was not
fit, per the method (only applied "if
warranted").

**Direct answer to the open question from task 2.4**: VIF is **low**.
`wind_max` is not redundant with the calendar terms (or with holidays,
economic, or marketing terms) — its counter-intuitive positive sign, and its
having survived the trend control only at the margin (p = 0.046, per
`04_weather/04_weather_report.md`'s post-trend-control update), **remains
unexplained by this check, not resolved by it.** The "wind is just tracking
finer within-month seasonal timing than the month dummies capture" theory
predicted high VIF; that prediction did not hold.

## A second, unprompted finding: calendar's own terms are highly collinear with each other

Not what this task was asked to check, but it emerged directly from the same
VIF table and is worth reporting rather than omitting: month dummies and
`week_of_year_sin`/`week_of_year_cos` are **highly collinear with each
other** (month VIFs ranging 3.2–27.5, `week_of_year_sin`/`cos` at 41.8/44.1
in the full formula) — expected, since both parameterize the same "time of
year" information at different resolutions. This doesn't bias the model's
overall fit or predictions, but it does inflate the standard errors of the
*individual* month/week-of-year coefficients, which is a plausible
contributing explanation for why `week_of_year_sin` has hovered at or near
non-significance across every task in this chain (tasks 2.2–2.6) — its
unique contribution beyond the month dummies is both genuinely small and
imprecisely estimated because of this collinearity. It is context for
interpreting the calendar coefficients; whether to keep the Fourier terms is decided
by the holdout ablation in `10_frozen_feature_set.md` (§1), not by this diagnostic.

## Discussion — what "unexplained" means here, precisely

Low VIF rules out one specific explanation (redundancy with calendar) for
`wind_max`'s counter-intuitive sign and marginal significance. It does not
rule out other explanations this task wasn't designed to test — e.g.,
redundancy with a term outside the current formula, a genuine but
counter-intuitive physical relationship (specific to Brazilian coastal/inland
conditions and this catalog, rather than a general boating-weather
assumption), measurement-proxy noise from the state-capital coordinate
lookup (a regional, not location-precise, weather proxy — see
`04_weather/04_weather_report.md`'s Method section), or simple sampling
noise given `wind_max`'s p-value sits right at the conventional 0.05
boundary. This task answers the specific redundancy question it was
designed to answer; it does not close the broader question of why the sign
is counter-intuitive.

## Recommendation — Checkpoint

**Weather is not redundant with calendar or with any other term currently in
the formula.** This does not change task 2.4's "not kept" accuracy verdict
(weather still doesn't clear the 2% MAPE-improvement bar), but it does
change what can honestly be said about `wind_max` for the client narrative:
it cannot be dismissed as "just calendar in disguise" — its
counter-intuitive sign is a genuine, currently-unexplained result, not an
artifact this check resolved.

**For task 2.10**: `10_frozen_feature_set.md` states this plainly rather than defaulting
to the seasonal-timing explanation — weather's exclusion from the final feature set is
justified on accuracy grounds (it does not clear the threshold) and marginal-significance
grounds (`wind_max` at p = 0.046, `temp_mean`/`precip_sum` not significant), not on a
redundancy claim this task tested and did not confirm.
