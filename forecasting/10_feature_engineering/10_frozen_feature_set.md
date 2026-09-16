# Frozen Feature Set — Stage 2 Feature Engineering (Task 2.10)

**This file is the fixed input for every Stage 3 (task 3.n) modeling
session from this point forward. No further changes without a new,
explicit team decision** — every task 3.n session reads this file rather
than re-deriving or re-testing features itself.

## Read this first: three different categories, not one list

A skim of this document (or of the individual task reports it summarizes)
can easily collapse everything into "features that were tried." They are
not all the same kind of thing. Three categories exist, and mixing them up
is the single most likely misreading of this whole stage's work:

| Category | What it means | What's in it |
|---|---|---|
| **A. Production feature set** | Ships to Stage 3 as model input columns. Earned its place via the ablation test below (removing it hurts the final formula's accuracy), not via its own >2% threshold (nothing individually cleared that bar). | Calendar's month dummies only — its Fourier terms were tested and dropped, see §1 |
| **B. Structural control** | Not a candidate feature at all. No keep/drop verdict, no causal hypothesis, always present regardless of any test outcome. Exists so every *other* coefficient can be trusted. | `trend` |
| **C. Not kept** | Tested properly (a real fit, a real MAPE comparison), came back below the bar, dropped from the production set. | Holidays, weather, economic, marketing |

A fourth, smaller category covers things that were never validly tested at
all (leakage, data unavailability, instrument limits) — see §5.

## 1. Production feature set (ships to Stage 3)

**Calendar's month dummies only**: `month_2`…`month_12` (dummy-encoded,
January reference). **`week_of_year_sin` and `week_of_year_cos` are
explicitly dropped** — see below; do not carry them forward by default just
because "calendar" earned a place in §3's ablation.

This is the *only* candidate feature group that survives into Stage 3, and
it earns its place through the ablation test in §3, not through its own
individual accuracy test (which it also failed to clear — see §4). Every
task 3.n model should include the month-dummy terms.

**The Fourier terms were tested directly, not dropped by inference from the
VIF finding alone.** Task 2.9 found `week_of_year_sin`/`week_of_year_cos`
heavily collinear with the month dummies (VIF up to 44), which raised the
question but didn't settle it — high VIF explains imprecision, not
necessarily that a term is worthless. A dedicated sub-ablation
(`output/calendar_fourier_ablation.csv`) fit the full final formula three
ways:

| Calendar variant | Final-formula MAPE |
|---|---|
| month + sin + cos (original) | 0.9594099 |
| month + cos only (drop sin) | 0.9594136 |
| **month only (drop sin + cos)** | **0.9593161** |

**Month-only wins outright** — it has the *lowest* MAPE of the three, not
just a tied or marginally-worse one. Keeping either Fourier term makes the
final formula's holdout accuracy very slightly *worse*, not better. This
resolves the ambiguity task 2.9 raised for `week_of_year_cos` specifically
(it was consistently significant in-sample across tasks 2.2–2.6 despite the
VIF finding, which could have argued for keeping it) — in-sample
significance here did not translate into holdout accuracy value, and the
direct holdout test is the one that decides inclusion in this stage's
methodology, not in-sample p-values. **Conclusion: `week_of_year_sin` and
`week_of_year_cos` are both dropped from the production feature set.**
`week_of_year_sin`'s redundancy with the month dummies (VIF 44) is still a
useful *explanation* for why it never independently mattered; it is not why
`week_of_year_cos` was also dropped — that was decided by the holdout
comparison above, which applies to both terms regardless of their
individual significance history.

## 2. Structural control (not a feature — always present)

**`trend`** (weeks elapsed since the panel's first period, continuous
linear term). Added in `_shared/panel_regression.py`'s `fit_and_evaluate()`
after task 2.5 found SELIC/IPCA's apparent effect was mostly a confound
with this project's known ~14–17%/year growth trend (`03_granularity_baselines`).
**Not a candidate feature**: no keep/drop verdict, no causal-hypothesis row,
not part of the ablation below. It exists so every other feature's
coefficient in this stage's regression could be trusted as a real,
population-level effect rather than a proxy for time.

**Heads-up for whoever starts Stage 3, not a new finding — just making sure
this doesn't need rediscovering**: this project has now shown the
multi-year growth effect twice, independently and consistently
(`03_granularity_baselines`'s ~14–17%/year finding, and this stage's own
`trend` coefficient, t≈32–50 across every task it appeared in — by far the
most consistently significant term in this entire regression). **"No trend
handling" is not a valid state for any of Stage 3's candidate models,
given how large and clean this effect has been shown to be twice over.**
Each model class needs it addressed in its own idiom, not necessarily
`trend`'s exact linear-term form: XGBoost/Random Forest need it as an
explicit engineered feature the same way this stage did (they have no
native trend concept); Prophet has a built-in trend component but its
default changepoint settings should be checked against this project's
smooth, consistent growth rather than assumed to fit it automatically;
ARIMA/SARIMA need the growth handled via differencing (an appropriate `d`/
`D` order) rather than a regressor. Whichever form each model uses, the
underlying fact to encode is the same one this stage independently
re-derived: consistent, smooth, ~14–17%/year growth, not a lumpy or
year-specific pattern.

## 3. The ablation — what actually determined §1

Per the plan's requirement, every layer that stayed in the cumulative chain
without individually clearing its own threshold got tested here: does the
**final assembled formula's** accuracy get worse if that layer is removed?
(`run_ablation.py`, full results in `output/ablation_results.csv`.)

| Layer | MAPE without it (relative to full formula) | Removing it changes MAPE by | Verdict |
|---|---|---|---|
| Calendar | 0.963624 | **+0.4392%** (accuracy gets *worse*) | **Keep** — the only layer whose removal has a non-trivial effect |
| Holidays | 0.959373 | −0.0038% (accuracy unchanged, marginally *better*) | Drop |
| Weather | 0.959255 | −0.0161% (accuracy unchanged, marginally *better*) | Drop |
| Economic | 0.959636 | +0.0236% | Drop (see note below) |
| Marketing | 0.959425 | +0.0016% | Drop |

(Full formula MAPE: 0.959410.)

**Only calendar's contribution (+0.44%) is large enough to treat as
meaningful — it's 19–280x the size of every other layer's contribution.**
Economic's +0.0236% and marketing's +0.0016% are both far smaller and not
distinguishable from noise at this scale; treating either as "the ablation
says keep it" would overstate what a difference this small actually shows.
Holidays and weather's negative contributions are unambiguous: removing
them doesn't just fail to hurt, it marginally *helps*, reinforcing their
individual "not kept" verdicts from §4.

This also directly confirms task 2.2's checkpoint reasoning: calendar
*specifically* was retained in the chain because of a named, verified
confound (holidays cluster by month), and it turns out to be the one layer
that genuinely earns a place in the final model — the ablation didn't just
rubber-stamp the retained-by-policy layers, it distinguished the one with a
real mechanism from the four retained by conservative-default policy alone,
none of which turned out to matter.

## 4. Tested and not kept (full detail)

All four of these were fit properly, evaluated against the >2%
MAPE-improvement threshold, and came back below it — this is a valid,
informative negative result for each, not an oversight:

- **Holidays** (`has_holiday`, `is_long_weekend`): 2.3's original report
  found both coefficients significant with opposite signs; after the trend
  control was added, **neither remained significant**. Ablation confirms:
  no measurable contribution to the final formula. See
  `03_holidays/03_holidays_report.md`.
- **Weather** (`temp_mean`, `precip_sum`, `wind_max`): none of the three
  cleared significance comfortably post-trend-control (`temp_mean` p=0.211,
  `precip_sum` p=0.237, `wind_max` p=0.046 borderline). **`wind_max`'s
  counter-intuitive positive sign remains genuinely unexplained** — task
  2.9's VIF check (low, 1.17–1.19) ruled out redundancy with calendar or
  trend as the explanation, correcting an earlier draft of the weather
  report that had prematurely claimed the trend control "resolved" this.
  It did not. This should be stated as an open, unresolved finding in any
  client-facing summary, not glossed over. See
  `04_weather/04_weather_report.md` (including its correction note) and
  `09_multicollinearity_check/09_multicollinearity_report.md`.
- **Economic** (`selic_rate`, `ipca_monthly_variation`): the task that
  surfaced the need for the trend control in the first place. Pre-fix,
  `selic_rate` showed an implausible +0.00266 coefficient (t=38.1, wrong
  sign); post-fix, it collapsed to **−0.00040** (t=−3.37, correctly signed)
  — small, credible, and worth keeping in the *narrative* as a genuine
  secondary finding (interest rates plausibly have a small dampening effect
  on this discretionary category) even though it doesn't ship as a
  production feature. `ipca_monthly_variation` lost significance entirely —
  its apparent effect was essentially all trend. See
  `05_economic/05_economic_report.md`.
- **Marketing** (`discount_rate`): a second confound was caught *before*
  reporting (not after) — an initial fit including `total_discount_amount`
  showed t-stats around 44, because that raw-sum term is mechanically tied
  to order volume and collinear with `discount_rate`. Dropped before
  fitting the reported version; `discount_rate` alone is unremarkable
  (t=−1.61, not significant). Reverse-causality check found no evidence
  discounts are timed to already-elevated demand. See
  `06_marketing/06_marketing_report.md`.

**Scope of all four negative verdicts, stated once rather than caveated
piecemeal**: holidays, weather, economic, and marketing all reflect
**catalog-wide averages** produced by a single pooled entity-fixed-effects
regression covering all 6,054 product×location series at once. **None of
the four rule out a real, segment-specific effect that this design cannot
see.** This project's own classification work
(`04_demand_classification`, "Strategy 1") found 96.8% of the catalog is
Intermittent by the CV² split — a pooled average across a catalog this
skewed can easily wash out an effect that's real and meaningful for a
specific segment (e.g. weather plausibly matters more for coastal/marine
products specifically, or a discount effect might be real for the Lumpy
3.2% tail's larger, less frequent purchases even if it's undetectable
averaged against the Intermittent majority). Task 2.3's report first raised
this for holidays specifically ("roughly cancel out" describes a
whole-catalog average, not zero effect everywhere); it applies with equal
force to weather, economic, and marketing, not just holidays. **A
per-segment re-test, referencing the Strategy 1 classification to split the
panel before fitting, is the natural follow-up if any of these four
features become newly relevant** — e.g. if a Stage 3 model's errors turn
out to concentrate in a specific segment these catalog-wide tests couldn't
resolve.

## 5. Not testable with current data or this instrument (task 2.7)

Distinct from §4 — no valid test was completed for either candidate here,
so there is no accuracy verdict to report, positive or negative. Applying
the three-way failure-mode taxonomy from `07_internal_inventory_report.md`
explicitly:

- **`is_demand_censored_flag` — leakage, not tested at all, never becomes
  usable in this form.** Computed as `qty_sold_gross >= stock_on_hand` —
  derived directly from the same day's own sales, the (near-)target
  variable itself. Excluded outright; reported only as a descriptive stat
  (0.01% of weeks flagged). This is categorically different from a
  confound: it doesn't produce a suspicious-looking result a check can
  catch after the fact, it's simply not a valid input, ever, regardless of
  data volume.
- **`is_stockout_day` — untestable with this instrument, not proven to
  have no signal.** Only 3 of 6,054 entities ever show any stockout at all
  (only 1,403 entities, 23.2%, have any stock-snapshot data whatsoever).
  `PanelOLS(entity_effects=True)` identifies coefficients from
  within-entity variation only, so a fit here would be driven by 3 series —
  confirmed empirically via `linearmodels`' own rank-deficiency error. **This
  is a limitation of this stage's fixed-effects design specifically, not
  evidence stockout timing has no relationship to demand.** A specification
  that can use between-entity variation (pooled OLS, a between/random-effects
  estimator) might still test it with the same 1,403-entity subset — out of
  scope for this checkpoint, but a legitimate open item (see §8).
- **Price-change — excluded for a third, different reason: data doesn't
  exist.** `dim_products` has only a single current price per variant, no
  price-history model anywhere in the project. Distinct from the leakage
  case above: even if price history existed, a price feature would carry
  its own, different endogeneity problem (price and demand are jointly
  determined), not a leakage problem.

**Forward-looking note for future work**: stock-derived features remain
*untested* for demand modeling — not "found to have no effect" — for
reasons distinct from but related to the original Phase 1 sparse-snapshot
finding (`01_data_exploration_summary.md` flag #3; `OVERVIEW.md`'s stage-01
summary notes stock-history sparsity as "deferred rather than solved").

## 6. COVID anomaly (task 2.8) — flagged for the team, not applied

Three independent checks (Phase 1's original revenue-based annual
comparison; a quantity-based reconciliation with a monthly seasonal-shape
overlay; a residual check from task 2.2's fitted calendar model) all found
**no detectable 2020–2021 anomaly** in level, shape, or model residuals.
**Recommendation carried forward as-is: flag, don't exclude or
down-weight.** No training-window change has been made anywhere in this
stage as a result. This is presented to the team for confirmation, per the
task's own framing — if the team has out-of-band knowledge warranting
different treatment, that's their call, not something this analysis can
resolve. See `08_covid_anomaly/08_covid_anomaly_report.md`.

## 7. The cumulative accuracy picture, stated honestly

**Of the six cumulative-chain tasks (2.2–2.7), five were testable and all
five came back "not kept" on their own individual accuracy test; the sixth
(2.7, inventory) was not testable at all.** Only one layer (calendar)
survives into the production feature set, and only via the ablation
criterion, not its own threshold. The cumulative improvement of the entire
five-layer formula over the zero-feature (entity-FE + trend) reference is
0.60% — itself well short of the 2% bar, and almost entirely attributable
to calendar alone.

This pattern was flagged as it emerged (`00_feature_backlog.md`'s cross-task
pattern check, written after task 2.6) as "the leading explanation so far,
not a settled conclusion": either this panel's grain (92.9%-zero at the
individual product×location×week level) is genuinely too noisy for any
single exogenous covariate to clear a 2%-relative bar, or the threshold
itself is miscalibrated for this specific MAPE regime (~96%, where 2%
relative is a ~1.9-point absolute ask — a much higher bar than the same
relative threshold would be at a lower MAPE level). The evidence accumulated
through task 2.9 leans toward the first explanation: two of five tested
layers (economic, marketing) initially looked like near-misses that turned
out to be confounds once properly specified, and every layer that survived
proper specification checking came back small. **This is Stage 2's
considered conclusion, not a certainty** — Stage 3's model comparison
(which will test fundamentally different model classes: tree-based,
Prophet, SARIMA) may still find nonlinear or interaction effects a linear
panel regression structurally cannot detect.

## 8. Open items for the team / future work (not resolved here)

- **Threshold interpretation**: this stage used relative MAPE-improvement
  throughout (`(prev-new)/prev > 0.02`). At the ~96% MAPE level observed
  here this is close to the absolute-percentage-point reading, but the two
  diverge more at other MAPE levels — worth an explicit team decision
  before task 2.10's threshold logic is reused elsewhere (e.g. Stage 3's
  own champion-selection criteria).
- **`wind_max`'s counter-intuitive sign** (§4) — genuinely unresolved, not
  explained by trend or by collinearity with calendar. Worth a follow-up
  investigation if weather is ever revisited (e.g. checking whether the
  4-state-capital weather proxy is too coarse, or whether the effect is
  real but small and specific to certain locations/products this
  catalog-wide regression can't isolate).
- **`is_stockout_day` untestability** (§5) — revisit if stock-snapshot
  density improves, or with a non-fixed-effects specification that can use
  between-entity variation.
- **`selic_rate`'s small, correctly-signed post-correction effect** (§4) —
  a genuine secondary finding worth keeping in the client narrative even
  though it isn't a production feature; not itself actionable further
  without new data.
- **Discount-amount-to-product allocation** (§4, marketing): this stage
  broadcast a location-week discount rate uniformly across every product at
  that location. A per-product or per-category allocation might reveal a
  real effect this aggregation diluted — not attempted here, since no
  reasonable allocation rule exists in current data without new
  assumptions.

## Provenance

Every number in this document traces to a specific script run and output
file under `forecasting/10_feature_engineering/<NN_*>/output/` or
`forecasting/10_feature_engineering/output/` (this ablation). See
`00_feature_backlog.md` for the full task-by-task narrative and the
methodological notes (structural control, cumulative-retention policy,
cross-task pattern check) this document summarizes.
