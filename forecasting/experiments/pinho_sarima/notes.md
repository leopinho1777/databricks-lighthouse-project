# SARIMA (task 3.5) — running notes

Working log, not a polished report. **Status: DONE.** Both `sarima_baseline` (d=1) and
`sarima_d0_trend` (d=0, `trend='c'` — the diagnostic-informed alternative) have real,
final full-catalog results. `sarima_d0_trend` wins on all 4 windows vs. `sarima_baseline`,
but **neither beats `seasonal_naive` (0/4 each)** — matches the tracker's own framing of
SARIMA as a benchmark, not the top performer. See "Final comparison" below for the numbers.
Both runs logged under `/Shared/02_model_comparison`.

## Hypothesis / scope for this session

Task 3.5's tracker wording: SARIMA as "a useful, well-established benchmark," explicitly not
expected to be the top performer given how feature-rich the other Stage 3 candidates' inputs
are. Scope stays a single fixed-order production run (`sarima_baseline`), not a tuning
exercise — that's XGBoost's job (3.3). An optional `sarima_seasonal_ar` variant is defined
but commented out in `RUNS`, to enable only if the timed pilot shows runtime headroom.

## Design decisions (written before any real run, per project convention)

- **Per-series, full catalog, not a subsample.** SARIMA is inherently per-`(product_variant_id,
  location_id)` series (unlike RF/XGBoost's pooled panel fit) — the tracker's own wording says
  "the product's own historical values." Full catalog (6,054 series × 4 cutoffs = 24,216 fits)
  is required, not optional: `evaluate.py`'s `compare_to_baseline()` checks the modeled
  `actual_total` per window against the full-catalog baseline's within 0.5% tolerance — a
  subsampled run would trip that drift warning by construction and the WAPE comparison
  wouldn't be meaningful.
- **Trend handling — differencing, not a regressor.** `10_frozen_feature_set.md` is explicit:
  *"ARIMA/SARIMA need the growth handled via differencing (an appropriate `d`/`D` order)
  rather than a regressor."* No `trend=` term, no `trend` column in `exog` — `d=1` (non-seasonal
  difference) carries the ~14-17%/year growth instead. Confirmed this is the right call rather
  than assumed: `diagnose_orders()` runs an ADF test on `log1p(qty)` at levels vs. first-differenced,
  to be run and its output recorded here before the production run (see "Pending" below).
- **Seasonal order — `D=1, s=52` applied directly, not diagnosed.** Weekly grain → annual
  seasonal period 52. The annual seasonality (Dec–Mar peak / Jun–Aug trough) is already
  independently confirmed twice in this repo (`01_data_exploration`, `03_granularity_baselines`),
  so this isn't re-tested here.
- **`seasonal_order=(0,1,0,52)` — seasonal differencing only, no seasonal AR/MA terms.**
  State-space cost scales with `s=52` regardless of how small `P`/`Q` are; dropping them to 0
  keeps the genuine "S" in SARIMA (the mandated differencing) without paying for `P`/`Q` terms
  at that state dimension across 24,216 fits. `sarima_seasonal_ar` (`(1,1,0,52)`) is defined as
  an opt-in stretch run if the pilot shows headroom.
- **`p, q` fixed at `(1,1)` for every series, not per-series searched.** No `pmdarima` in this
  project's dependencies (confirmed via `pyproject.toml`/`uv.lock`) — order selection is
  statsmodels-only, matching the tracker's "Tool/Service: statsmodels" note. `(1,1)` is checked
  against `(0,1)`/`(1,0)` via AIC on the portfolio-aggregate series in `diagnose_orders()`
  (pending — see below), not per-series, to keep the production loop simple and the fit count
  bounded for a single-benchmark-run scope.
- **Month dummies (`month_2..month_12`) kept as `exog`, alongside `D=1` differencing — not
  either/or.** This resolves an open question the frozen-feature-set doc leaves for each
  model class: the dummies are deterministic, fixed-shape calendar effects (already
  ablation-proven to matter in Stage 2); `D=1` differencing instead captures whatever
  *stochastic* year-over-year seasonal drift a fixed dummy can't adapt to across 5+ years of
  data. Both mechanisms address genuinely different things, so both are kept.
- **Internal grain: weekly**, matching the project's recommended default
  (`03_granularity_baselines`: daily is 73%-zero and too sparse). `HORIZON_WEEKS=13` /
  `STRADDLE_LAG=6 days` copied verbatim from `train_random_forest.py` — same Tuesday-cutoff /
  Monday-anchored-week straddle-week exclusion, already debugged there; expect the same
  actual-demand drift on the 2025-07-01 window that RF's notes.md measured and explained
  (structural consequence of the leak-safe exclusion, not a bug).
- **Fit robustness**: `enforce_stationarity=False, enforce_invertibility=False,
  simple_differencing=True`, `maxiter=50` — bounds per-fit cost and avoids hard failures on the
  catalog's many near-flat/near-zero series (96.8% Intermittent, 92.9%-zero at this grain).
- **Fallback rule (predetermined, not re-litigated per series)**: on any fit exception, forecast
  0 for the horizon — mirrors `train_random_forest.py`'s documented "no history → forecast 0"
  convention. The failure is recorded per (series, cutoff) in `fit_diagnostics.csv`
  (`fallback=True`, `error=<message>`), never silently swallowed.
- **"Converged" is a ConvergenceWarning check, not a strict optimizer flag.** statsmodels
  doesn't expose one consistent, optimizer-agnostic convergence indicator on the results object
  across all its optimizers — `fit_one_series()` instead catches `ConvergenceWarning` explicitly
  during `.fit()` and reports its absence as `converged=True`. This is a weaker signal than a
  true convergence check and is logged as `pct_non_converged`, tracked separately from
  `pct_fit_failures` (exceptions) rather than conflated with it.
- **Model artifacts: 2-3 fixed exemplar series only, not all 6,054.** `_select_exemplars()`
  picks, once, by volume from `demand_classification.csv`: the catalog's single highest-volume
  series overall, plus the highest-volume series in each of the two segments present in this
  catalog (Intermittent/Lumpy). Refit sequentially (not through the parallel dispatch) at the
  final cutoff only, and logged via `mlflow.statsmodels.log_model()`. Per-series fit diagnostics
  for the full catalog live in `fit_diagnostics.csv`, not in MLflow model artifacts.
- **Reused verbatim, not reimplemented**: `get_cutoffs()`, `evaluate()`, `compare_to_baseline()`
  from `experiments/_shared/evaluate.py`; `get_table_version()`, `get_library_versions()` from
  `experiments/_shared/repro.py`; `init_mlflow_experiment()`, `load_weekly_panel()`,
  `MARTS_SCRATCH` from `10_feature_engineering/_shared/panel_regression.py`. `EXPERIMENT_PATH =
  "/Shared/02_model_comparison"`, matching `eros_randomforest`.
- **`SAMPLE_ENTITIES` env var** (same convention as `eva_regression/run_panel_regression.py`)
  restricts to a small, deterministic entity subset for a fast pipeline check. Results from a
  sampled run are explicitly not comparable to the baseline and the drift warning is expected
  to fire — this is for mechanics-checking only, not a substitute for the full-catalog run.

## Bugs found while testing

1. **`joblib`'s default `loky` backend re-executes the whole script's module scope in every
   worker process.** Confirmed via the offline smoke test: after the main process finished and
   printed its final line, several more copies of `train_sarima.py`'s module-level
   `print(f"Peak-season months...")` appeared — each one a `loky` worker re-importing the
   script from scratch as it started up, including a fresh call to `load_weekly_panel()`. This
   is standard behavior for Python's "spawn" multiprocessing start method (child processes
   reconstruct `__main__` by re-running the launching script), not a joblib-specific bug.
   **First fix attempt — switched to `backend="threading"` — was wrong.** Threading avoids the
   re-import problem (no new process, no module reconstruction) but was measured directly (a
   controlled serial-vs-threaded timing comparison on an identical 24-series batch) to give
   **no real speedup: 0.84x, i.e. slightly *worse* than serial** — `SARIMAX.fit()`'s
   `scipy.optimize` loop doesn't release the GIL enough at this per-fit problem size for
   threads to help. **Actual fix**: kept the default process-based (`loky`) backend for real
   parallelism, and instead moved every warehouse/CSV-touching top-level statement
   (`load_weekly_panel()`, peak-month computation, `demand_classification.csv` read, exemplar
   selection) out of bare module scope and into a new `_setup()` function, called explicitly
   from `if __name__ == "__main__":` (or a test harness). Worker processes now re-import the
   script cheaply — function/constant definitions only, `_setup()` never runs in them — while
   the parent process still gets true multi-core parallelism. Confirmed on the real warehouse:
   the 100-series pilot dropped from **80.1s (threading, 0.801s/fit)** to **12.1s (process,
   0.121s/fit)** for the identical work — a ~6.6x speedup on this 8-core machine, and no
   duplicate module-scope output in either the offline smoke test or the real pilot run.
2. **An all-NaN series does NOT raise inside `SARIMAX.fit()`** with
   `enforce_stationarity=False, enforce_invertibility=False` — it silently fits degenerate
   near-zero params instead of erroring (verified directly: `aic=28.0`, params `≈[0,0,0]`, no
   exception). Not a bug worth guarding against here: the production panel is a dense,
   zero-filled global spine (`fact_demand_daily`), so no series in practice will be all-NaN —
   but it means `fit_one_series()`'s `except` branch cannot be relied on to catch a
   *degenerate-but-not-erroring* series. The fallback path was instead verified with a genuine,
   always-raising failure mode (mismatched `exog` shape) — see below.

## What was actually verified this session (offline, synthetic 3-series panel, no warehouse)

Ran against a synthetic panel (`P1/L1`, `P2/L1`, `P3/L2`, 2020-01-06..2026-01-05, seasonal +
trending + noisy), with `panel_regression.load_weekly_panel()` stubbed so no DB connection was
needed:

1. `add_calendar()`: month-dummy columns present, no `trend` column — OK.
2. `fit_one_series()` on a well-behaved series: clean fit, 13-week forecast, all values ≥ 0 —
   OK (though `converged=False` on this tiny synthetic series at `maxiter=50` — worth watching
   on the real run; see Pending below).
3. `fit_one_series()` fallback path (mismatched `exog` shape → genuine exception): correctly
   returns `fallback=True`, zero forecast, captured error message, no crash — OK.
4. `mlflow.statsmodels.log_model()` / `load_model()` round-trip: **loaded back successfully
   without needing any env var override** — the pickle-load-disallowed gotcha the design phase
   flagged as a risk (by analogy with RF's `skops` surprise) did **not** reproduce with this
   installed mlflow version (3.16.0). Documented here so it isn't re-investigated from scratch
   later, and so 3.7/3.8 knows this was checked, not assumed.
5. End-to-end `run_walk_forward()` + `log_run()` on the synthetic catalog: ran without
   exceptions, wrote all 5 output CSVs, logged a run to a local file-based MLflow tracking store.
   Exemplar-entity lookups correctly no-op'd (synthetic entity ids don't match the real
   `demand_classification.csv`, so all three exemplar artifacts were skipped with a warning, not
   a crash) and the segment join correctly warned "3/3 series had no match" rather than
   silently producing empty results. The synthetic run's actual-demand drift warning
   (91.72%) and near-100% WAPE numbers are expected and meaningless — 3 synthetic series vs. a
   real baseline computed over the full catalog, not a signal about the real model.
   These smoke-test CSVs/MLflow run were local and have been deleted from `output/` — they are
   not real results.

Ruff (`uv run ruff check forecasting/experiments/pinho_sarima/train_sarima.py`): clean.

## Auth — no interactive login was actually needed

`~/.dbt/profiles.yml`'s `dev` target already has a working PAT (`auth_type: token`), which
`db_connection.py`/`panel_regression.py` use directly (`profile.get("token")` short-circuits
before the OAuth browser-login path). Verified with `python forecasting/_shared/db_connection.py`
(`select 1 as ok` round-trip) — succeeded immediately, no `databricks auth login` needed for
this workflow. (That command is documented elsewhere in this repo for the *ingestion* bundle's
Databricks Connect tests, which is a separate auth mechanism from this forecasting workstream's
direct `databricks-sql-connector` + PAT approach.)

## Timed pilot — run against the real warehouse (`python train_sarima.py --pilot 100`)

Real peak months from the actual catalog (differs from the earlier synthetic smoke test, as
expected): `[1, 2, 3, 4, 10, 11, 12]`. Exemplar entities: `top_volume`/`intermittent` both
`('24','3')` (the top-volume series happens to be Intermittent), `lumpy` → `('567','6')`.

**Result: 100 series, 12.1s total, 0.121s/fit → extrapolated full-catalog (24,216 fits)
wall-clock ≈ 49.0 minutes**, already reflecting real `n_jobs=-1` process-based parallelism
(8 cores; see "Bugs found" above for how this number went from a wrong ~323 min estimate under
threading to this real, process-parallel one). If anything this is conservative: the pilot's
100-task batch amortizes per-worker startup overhead worse than each cutoff's real 6,054-task
batch will.

**Go/no-go decision: GO on the full run as currently configured** — ~49 minutes is a
reasonable single-session wall-clock for a benchmark deliverable; no further simplification
(e.g. dropping `q` to 0) is needed before attempting the full run. `sarima_seasonal_ar`
(the optional `seasonal_order=(1,1,0,52)` stretch run) also looks affordable at this rate if
wanted later, though it wasn't pilot-tested separately — it would need its own timing since
adding seasonal AR/MA terms multiplies per-fit state-space cost.

## Order diagnostics — real result contradicted the `d=1` design assumption

`python train_sarima.py --diagnose` (real warehouse, `_setup()` gives real `panel`/`_segments`):

- **Portfolio aggregate, ADF on levels (log1p)**: `regression="c"` → stat=-4.765, p=0.0001;
  `regression="ct"` (trend-aware, the more appropriate spec given the known growth) →
  stat=-7.597, p≈0.0000. **Both robustly reject the unit-root null** — i.e. the aggregate
  looks stationary already, contradicting the original assumption ("expected to fail... per
  the twice-confirmed growth").
- **Per-series, stratified sample (10 Intermittent + 10 Lumpy, split by volume, 20 total)**:
  **20/20 reject the unit-root null** at levels too (`p` from 0.0067 down to <0.0001; most
  series' `stat` around -17 to -19, far past the ~-2.9 critical value).
- **diff(1) ACF[1] = -0.352**: the textbook over-differencing signature — differencing a
  series that didn't need it introduces artificial negative lag-1 autocorrelation.
- **AIC over `(p,q) ∈ {(0,1),(1,0),(1,1)}` at `d=1`**: `(1,1,0)` best at -137.7, `(1,1,1)`
  close behind at -137.0, `(0,1,1)` worst at -136.2 — all close together, `(1,1)` kept as
  originally planned (differences between these three are small relative to the `d`
  question).

**Why this isn't really a contradiction of the known growth trend**: ADF's stationarity
alternative includes *trend-stationary* processes (deviations from a smooth trend that don't
wander further away over time) — this project's growth has specifically been characterized as
smooth and consistent (not a random walk), which is exactly that shape. For individual series,
which are 92.9%-zero at weekly grain, a demand series pinned near zero with frequent
zero-crossings is close to mechanically going to reject "random walk" behavior regardless of
trend, since a true unit-root process would need to wander unboundedly away from zero.

**The catch that matters more than the ADF result alone**: `d=0` with no trend term would
silently drop the model's only mechanism for tracking growth (`D=1` seasonal differencing
alone leaves a non-zero *mean* in the seasonally-differenced series — last year same-week vs.
this year same-week isn't zero on average, it's the growth — and SARIMAX only estimates that
mean if told to via `trend=`). Checked directly: `SARIMAX(..., order=(1,0,1),
seasonal_order=(0,1,0,52), trend="c", simple_differencing=True)` fits cleanly on 5 real
sampled series with AIC comparable to the `d=1` config (no errors, no `validate_exog`
conflict since `exog` is month dummies with no constant column) — `trend="c"` is added on the
*differenced* scale per SARIMAX's own model spec (`Δ^d Δ_s^D y_t = A(t) + ...`), so it
correctly captures drift after seasonal differencing without double-handling growth alongside
`d=1`.

**Decision (per explicit direction, not unilaterally resolved)**: rather than silently
overriding `10_frozen_feature_set.md`'s "handle growth via differencing" instruction based on
one diagnostic, **both configs are run and logged, and the comparison against
`seasonal_naive_genuine_91d_v2` decides**:
- `sarima_baseline`: `order=(1,1,1)`, `seasonal_order=(0,1,0,52)`, no trend — the originally
  planned config, matching the frozen-feature-set doc's literal instruction.
- `sarima_d0_trend`: `order=(1,0,1)`, `seasonal_order=(0,1,0,52)`, `trend="c"` — the
  diagnostic-informed alternative (no non-seasonal differencing, growth captured via SARIMAX's
  own trend term instead).

Both logged to `/Shared/02_model_comparison` under their own run names; `notes.md` records the
actual results below once run.

## Full run — `sarima_baseline` results (first attempt; `sarima_d0_trend`'s numbers from this attempt were discarded — see bug below, corrected numbers in "Final comparison")

`python train_sarima.py sarima_baseline sarima_d0_trend`, full catalog, both configs, ~51 min
wall-clock for the pair (close to the ~49 min/config pilot estimate).
Run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/5890e375e2884933977dc31ecd470235

Portfolio WAPE per cutoff (`sarima_baseline` vs. `seasonal_naive`):

| cutoff | SARIMA (d=1) | seasonal_naive | delta |
|---|---|---|---|
| 2024-12-31 | 93.99% | 78.84% | +15.14pp worse |
| 2025-04-01 | 110.57% | 84.43% | +26.14pp worse |
| 2025-07-01 | 115.00% | 88.05% | +26.95pp worse (has the same ~9.49% actual-demand drift caveat RF's notes.md already measured/explained for this window — structural consequence of the straddle-week exclusion, not a bug) |
| 2025-09-30 | 96.76% | 79.89% | +16.87pp worse |

**`beats_baseline`: 0/4** — matches the tracker's own framing of SARIMA as "a useful benchmark,
not expected to be the top performer." `pct_fit_failures=0.00%` (no exceptions),
`pct_non_converged=63.34%` (majority of fits raised a `ConvergenceWarning` at `maxiter=50` —
plausible given the fixed, unsearched order and the catalog's heavy intermittency; a real
caveat on how much to trust these numbers, not just a formality — see Open items).
Per-segment RMSE/bias: intermittent 7.05/3.20, lumpy 5.79/2.27 (both positive bias =
under-forecasting on average, consistent with RF's finding of the same failure mode).

## Bug found while executing the full run: silent numerical blowup, not a Python exception

`sarima_d0_trend`'s first full run produced portfolio WAPE values in the **1e125–1e189 range**
— obviously not real. Root-caused directly (not guessed): pulled `window_totals.csv` and found
**only 5 of 24,216 fits** had `pred > 1e6` (max: `3.496e+189`, for `('543','4')` at cutoff
2025-04-01, a series whose entire training history never exceeded 8 units/week). The other
24,211 predictions were completely reasonable (median ≈ 0.88). Because portfolio WAPE sums
absolute error over total actual demand, a handful of ~1e100+-scale predictions completely
swamp the metric despite being a vanishingly small fraction (0.02%) of fits.

**Cause**: `enforce_stationarity=False` (needed generally, to avoid hard failures on the
catalog's many near-flat/near-zero series) lets the optimizer choose an explosive AR root for
a small minority of series; without `d=1` differencing to constrain that, a 13-step-ahead
forecast from an explosive root compounds exponentially. The fit itself raises no exception —
`fit_one_series()`'s `except` branch never saw this, because there was nothing to catch. This
is the same underlying category of risk already flagged in "Bugs found" item 2 above (a
"successful" fit silently producing garbage), now confirmed as a real, live-run failure mode
rather than a hypothetical.

**Fix**: added a sanity-bound check in `fit_one_series()` — `sane_cap = max(1000.0, 100 *
series' own historical peak week)`; any non-finite value or any predicted week exceeding that
cap is now treated as a fit failure (routed through the existing fallback-to-zero path, with a
descriptive error message), not silently trusted. Verified directly against the known-bad
`('543','4')` series: previously predicted `3.496e+189`, now correctly falls back with
`error="unstable forecast: max pred=3.496e+189 exceeds sane cap 1000.0 ..."`.
`sarima_d0_trend` was re-run with this fix; only that config needed rerunning
(`sarima_baseline`'s run was already clean — `d=1` differencing structurally prevents this
failure mode, since there's no undifferenced explosive root to extrapolate from).

## Final comparison — `sarima_d0_trend` (post-fix) vs. `sarima_baseline`

Re-run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/0e6cf3a743f54677b9ddb0733cd1c150
`pct_fit_failures=0.02%` (5/24,216 — exactly the known-bad series from the blowup, now
correctly caught and routed to the zero-forecast fallback instead of corrupting the metric).

| cutoff | sarima_baseline (d=1) | sarima_d0_trend (d=0, trend='c') | delta | seasonal_naive |
|---|---|---|---|---|
| 2024-12-31 | 93.99% | **93.37%** | -0.62pp | 78.84% |
| 2025-04-01 | 110.57% | **105.12%** | -5.45pp | 84.43% |
| 2025-07-01 | 115.00% | **109.27%** | -5.73pp | 88.05% |
| 2025-09-30 | 96.76% | **92.64%** | -4.12pp | 79.89% |

**`sarima_d0_trend` beats `sarima_baseline` on all 4 windows** (WAPE lower by 0.6–5.7pp
every time, largest gains on the two middle cutoffs) — the diagnostic-informed hypothesis
holds up under the actual "let the numbers decide" test: `d=1` was over-differencing an
already-largely-stationary catalog, and `trend='c'` (with `d=0`) captures the growth drift
more efficiently. Per-segment RMSE/bias is close between the two (intermittent 6.84/3.71 vs.
7.05/3.20; lumpy 5.50/2.66 vs. 5.79/2.27) — the win shows up mainly in the portfolio-level
WAPE, consistent with `d0_trend` handling the catalog's aggregate growth better without
uniformly improving every individual series.

**Neither beats `seasonal_naive` on any window (0/4 for both)** — matches the tracker's own
framing of SARIMA as "a useful, well-established benchmark," not expected to be the top
performer. `sarima_d0_trend` is the stronger of the two SARIMA candidates and the one worth
carrying into any later 3.7/3.8 cross-model comparison, but the champion for this catalog
remains `seasonal_naive_genuine_91d_v2`, same as every other Stage 3 candidate tested so far
(RF also lost 0/20 across all its configs).

## Open items for the team

- Order search here is a single fixed `(p,d,q)(P,D,Q,s)` for the whole catalog, not per-series
  — a legitimate benchmark-scope simplification (see Design decisions), but a genuine
  per-series order search (e.g. adding `pmdarima` as a dependency, or a per-series AIC grid) is
  a real follow-up if SARIMA turns out competitive enough to be worth tuning further.
- `converged` is a ConvergenceWarning-based proxy, not a strict solver-convergence flag — any
  later comparison quoting `pct_non_converged` from this run should carry that caveat.
- Exemplar-model artifact selection is by raw volume only (`total_qty_sold_net`), not by
  fit quality — a series could be an exemplar and still be a `fallback`/non-converged fit; worth
  a quick check once the full run's `fit_diagnostics.csv` exists.
- **The silent-numerical-blowup failure mode (see "Bug found") is a general SARIMAX gotcha,
  not specific to this script.** Any future session fitting `SARIMAX` with
  `enforce_stationarity=False` across many series (e.g. a per-series order search, if 3.7/3.8
  or a future session pursues that) should carry forward the same sanity-bound-on-output
  discipline `fit_one_series()` now has — a "successful" `.fit()` call is not sufficient
  evidence the forecast is trustworthy.
- `sarima_d0_trend` (d=0, `trend='c'`) is the stronger SARIMA variant found this session, but
  it deviates from `10_frozen_feature_set.md`'s literal "handle growth via differencing"
  instruction for ARIMA/SARIMA. Worth a short explicit team note if `sarima_d0_trend` (rather
  than `sarima_baseline`) is the one carried forward into 3.7/3.8, so the deviation is a
  visible, acknowledged decision rather than something someone has to rediscover from this
  file later.
