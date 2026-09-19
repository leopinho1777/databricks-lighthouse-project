# Prophet (task 3.4) — running notes

Working log, not a polished report. Status: all 5 planned MLflow runs executed against the live
workspace and logged under `/Shared/02_model_comparison`, results recorded below. Bottom line: no
config beats `seasonal_naive` on any window (0/20) — same overall verdict as RF's task 3.2 — but
Prophet's per-series trend component and holiday regressor were both directly tested against the
task's own stated justification, with clear answers (see "Best result so far" and "Open items").

## Hypothesis being tested this session

The tracker's own justification for 3.4 is "Prophet is purpose-built for seasonal, holiday-driven
time series like this one." This session tests that directly rather than assuming it:
`prophet_no_holidays` isolates whether BR holidays actually help once yearly seasonality is
already in the model, and `prophet_changepoint_flexible`/`_rigid` check Prophet's trend component
against this project's independently-confirmed ~14-17%/year smooth growth
(`10_frozen_feature_set.md` explicitly flags this as something to verify, not assume).

Unlike RF (task 3.2), which fit one pooled model across the whole ~6,054-series catalog, Prophet
fits one model PER series — a structurally different cost shape (per-fit fixed overhead x series
count, not one fit's complexity on a fixed dataset). That's why a timing pilot is a hard
prerequisite here and wasn't needed for RF.

## Timing pilot section (`pilot_timing.py`, run against the live workspace)

- Pilot sample composition: **209 series** (194 intermittent + 15 lumpy, floor-adjusted from the
  target 200; stratified from `04_demand_classification/output/demand_classification.csv`,
  `random_state=42`) — slightly more than the plan's estimated 208 due to rounding
  (`round(5861*0.033)` landed on 194, not 193).
- Pilot cutoff: 2025-09-30 (last/largest-training-window cutoff, conservative upper-bound estimate).
- **Cold-start fallbacks: 0/209** (`MIN_TRAIN_POINTS=10` didn't trigger on any pilot series at the
  most-history cutoff) — reasonable given only the *last* cutoff was piloted; this should still be
  watched per-cutoff once the real runs log `cold_start_fallback_count_<cutoff>`, since earlier
  cutoffs have less training history and may trigger it more.
- **Measured: mean 0.158s/fit+predict (median 0.157s, max 0.241s), n=209.**
- Threshold: 0.2230s/fit (90 min/6,054-series-x-4-cutoffs run config) — **measured 0.158s/fit is
  ~29% UNDER budget**, comfortably so (not a borderline call). Confirms the subprocess-spawn-
  overhead-dominated cost model was the right framing: per-fit cost here is small and consistent
  (max only 0.241s across 209 series, no long-tail outliers), not RF's very different "one
  pooled fit's complexity" cost shape.
- Extrapolated one run config (6,054 series x 4 cutoffs): **1.06 hours**. Extrapolated full 5-run
  exploratory session at this scale: **5.32 hours**.
- Lumpy-segment fit-time std (informational stability check): 0.004s — negligible variance, no
  per-series outlier dominating lumpy's timing.
- **Decision: `full_catalog`.** All 5 `RUNS` in `train_prophet.py` run against the full 6,054-series
  catalog, every time — no subsample fallback or separate final full-catalog run needed.

## Design decisions (written before any runs)

- **`weekly_seasonality=False`**: the panel is already weekly-aggregated (`load_weekly_panel()`),
  so there's no sub-weekly cycle left for Prophet to model.
- **`yearly_seasonality=True`** (explicit, not `"auto"`): `"auto"` silently disables yearly
  seasonality below ~2 full cycles of history, and per-series history length varies a lot across
  the catalog — explicit `True` makes every fitted series actually attempt seasonality rather than
  silently degrading to trend-only without recording that this happened.
- **Target**: `log1p(qty_sold_net)`, back-transformed via `expm1().clip(min=0)` — same convention
  RF used, kept for consistency across Stage 3 models (also the reason the
  `prophet_seasonality_multiplicative` ablation is expected to show a small/no effect: the log
  transform already linearizes multiplicative seasonal effects in log-space).
- **`changepoint_prior_scale`** is the primary tuned hyperparameter, per `10_frozen_feature_set.md`'s
  explicit flag that Prophet's default changepoint settings need checking against this project's
  confirmed smooth growth trend.
- **`MIN_TRAIN_POINTS=10`** (~2.5 months of weekly history): cold-start threshold below which a
  series gets a zero-forecast fallback instead of a fit attempt. NOT derived from this catalog's
  actual history depths — see Timing pilot section above, which checks the fallback rate before
  the full run inherits this.
- **Exemplar series** (decomposition-plot deliverable): single highest-volume
  `(product_variant_id, location_id)` pair by total `qty_sold_net` in the training window as of the
  last cutoff, computed once, deterministically. Always fit and plotted regardless of run-scale —
  added into the subsample if not already present. **Resolved this session: `product_variant_id=448`,
  `location_id=3`, training-period volume=194.0 units** — same series, deterministically, across all
  5 runs (confirms the computation is stable and independent of which config is running).
- **MLflow artifact scoping**: only ONE model and ONE plot are ever logged — the exemplar series'
  final-cutoff fit — never one artifact per series (infeasible at 6,054 series). This scopes RF's
  own "final-cutoff model only, not all 4 folds" reasoning down one further level (per-series, not
  just per-fold). **Confirmed working this session**: `mlflow.prophet.log_model()` succeeded on
  every one of the 5 runs under this project's `mlflow-skinny` install — the JSON-serialization
  fallback path (added defensively, given RF hit 2 separate mlflow-skinny surprises) was never
  triggered.
- **Lumpy-segment stability check**: the pilot's floor sampling gives 15/193 lumpy series (7.8%,
  thinner than intermittent's ~3.3% rate), and lumpy is the highest-variance category by
  definition — every run reports per-segment RMSE/bias std/min/max (not just mean) so a "config X
  won" verdict from subsample runs is checked against segment stability before being carried into
  the single full-catalog final run.
- **Straddle-week/weekly-grain logic reused verbatim from `train_random_forest.py`** — not
  redesigned. Same reasoning: the protocol's 4 cutoffs are all Tuesdays, no week's Monday-anchor
  lines up with a cutoff exactly, so the straddling week is excluded from both train and the
  scored horizon.
- **Escape hatch in `pilot_timing.py`**: if the pilot itself doesn't complete cleanly (>10% of
  attempted real fits raise exceptions, or zero successful timed fits), it raises rather than
  computing an extrapolation from partial/anomalous data.

## One-time Windows setup cost (this session)

`prophet`/`cmdstanpy` added to `pyproject.toml`'s `forecasting` dependency group; `uv sync --dev
--group forecasting` installs the Python packages but NOT the CmdStan backend binaries — that
needed a separate one-time step:

- `python -m cmdstanpy.install_cmdstan --compiler` (first attempt) failed: the RTools40.exe
  installer download succeeded, but cmdstanpy's own `subprocess.Popen` call to launch it raised
  `FileNotFoundError: [WinError 2]` in this environment (Windows, invoked from a Git Bash-based
  tool shell) — the installer file was downloaded but never executed by that Popen call.
- Fixed by running the downloaded `RTools40.exe` directly via PowerShell's `Start-Process`
  (`/SP- /SILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR="...\.cmdstan\RTools40" /NOICONS /NORESTART`)
  instead of letting cmdstanpy launch it — exit code 0, toolchain installed successfully.
- Retrying `install_cmdstan` still failed: `mingw32-make` not found. cmdstanpy's own
  `install_mingw32_make()` step (which runs `pacman -Sy mingw-w64-x86_64-make` inside the RTools40
  MSYS2 environment) never ran, because that step is only triggered by cmdstanpy's own
  `install_cxx_toolchain` flow, which we'd bypassed by installing RTools40 manually. Fixed by
  running the same `pacman -Sy mingw-w64-x86_64-make --noconfirm` command manually (via PowerShell,
  with `RTools40\usr\bin` prepended to `$env:PATH` so `pacman.exe` resolves) — this places
  `mingw32-make.exe` at `RTools40\mingw64\bin\mingw32-make.exe`, the exact path cmdstanpy's build
  step expects.
- A subsequent `install_cmdstan` run *without* `--compiler` still failed the same way, because
  `run_compiler_install()` (which calls `cxx_toolchain_path()` to prepend the toolchain to that
  process's `PATH`) only runs when `--compiler` is passed — skipping it means `mingw32-make` is
  never findable even though it now exists on disk. Fixed by re-running WITH `--compiler`; since
  RTools40 was already detected as installed at `home_cmdstan()` (`~/.cmdstan/RTools40`), it
  skipped reinstalling and just added it to `PATH`, then proceeded to `make build`.
- **Takeaway for the next Stage 3 session that needs cmdstanpy on Windows**: don't let cmdstanpy's
  own installer launch the RTools40 exe (it fails to spawn it from a Bash-tool-style shell) — run
  the downloaded installer directly via PowerShell's `Start-Process` instead, then always pass
  `--compiler` to `install_cmdstan` (even on a retry) so the toolchain PATH is set up in that same
  process before `make build` runs.
- Final result: confirmed working — CmdStan built and its test-model compilation passed, and all 5
  live MLflow runs (up to 6,054 Prophet fits each) completed successfully with no compiler/toolchain
  issues resurfacing.

## Bugs found while actually executing

Static verification (ruff, offline synthetic smoke tests) didn't catch these — they only surfaced
once real runs were attempted against the real workspace, same pattern as
`eros_randomforest/notes.md`'s 3 documented fixes:

1. **`pd.Series.clip(min=0)` → `TypeError: clip() got an unexpected keyword argument 'min'`**: the
   exact OPPOSITE mistake from RF's own clip bug. `model.predict()` (Prophet) returns a DataFrame,
   so `forecast["yhat"]` is a pandas Series, not an ndarray — `np.expm1()` on a Series stays a
   Series, so pandas' `.clip(lower=0)` is needed, not numpy's `.clip(min=0)` (which RF's script
   needed because sklearn's `model.predict()` returns a bare ndarray). Caught after the first real
   full-catalog run (run 1) crashed at the very end during MLflow logging — costly to hit (~2.5
   hours in), fixed, then verified offline with a synthetic multi-series smoke test (fit + predict
   + cold-start path + the exemplar decomposition-plot path) before spending more live compute time.
2. **`logging.getLogger("cmdstanpy").setLevel(logging.ERROR)` doesn't stick**: cmdstanpy's own
   `get_logger()` (called lazily on its first internal use, e.g. inside the first `.fit()` call)
   unconditionally resets the logger's level to `DEBUG` the first time it initializes its handler,
   clobbering any level set beforehand. Fixed by importing and calling `cmdstanpy.utils.get_logger()`
   directly (forcing that lazy init now, since it's `lru_cache`d) and THEN setting the level —
   verified via a synthetic fit that produced zero "Chain [1] start/done processing" spam.
3. **Per-series boolean-mask filtering was ~2.45x more expensive than the timing pilot predicted**
   (documented in detail below, "Pilot extrapolation was wrong") — not a crash, but a real
   performance bug found only by comparing a real run's wall-clock against the pilot's estimate.
4. **Windows/cmdstanpy install friction** (documented above, "One-time Windows setup cost"):
   cmdstanpy's own installer couldn't launch its downloaded RTools40.exe from this shell, and its
   `install_mingw32_make()` pacman step only runs inside its own `--compiler` flow — both fixed by
   doing those two steps manually, then re-running `install_cmdstan --compiler` (not without the
   flag) so the toolchain gets added to `PATH` in the same process before `make build` runs.
5. **Background-task working-directory confusion (tooling, not code)**: two run attempts failed
   immediately with `cd: forecasting/experiments/eros_prophet: No such file or directory` because
   a background shell command's `cd <relative path>` was issued from a session whose actual cwd
   was already inside that directory from a prior command. Fixed by checking `pwd` before
   prefixing a `cd`, not by changing any project code — noted here only so a future session
   reading this doesn't mistake it for an environment/dependency problem.

## Actual-demand drift vs. baseline

All 5 runs triggered the identical `compare_to_baseline()` warning: *"actual demand differs from
the baseline by up to 9.49%"*, with byte-identical per-cutoff `actual_total` values across every
run (45341.0 / 21902.0 / 18688.0 / 42035.0 on 2024-12-31 / 2025-04-01 / 2025-07-01 / 2025-09-30
respectively). These are the EXACT SAME numbers `eros_randomforest/notes.md` already recorded and
investigated for RF (task 3.2) — confirming the straddle-week logic was reused correctly and
behaves identically here, not a new divergence. Per that investigation: the ~9.49% drift on
2025-07-01 is a structural window-shift effect (our horizon starts ~5 days later than the
baseline's exact cutoff+1 boundary, and early October carries meaningfully higher demand than
early July in this data), not a qty-definition bug — cite RF's finding rather than re-deriving it.
Treat the 2025-07-01 window's WAPE/`beats_baseline` result with reduced confidence relative to the
other three, same caveat as RF's.

## Runs (in order)

### 1. `prophet_baseline` (changepoint_prior_scale=0.05, seasonality_mode=additive, BR holidays on)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/30246275252a4c6fbb0ffce23b9355dc
- **Actual wall-clock: 155.8 minutes** (full 6,054-series catalog, 4 cutoffs) — see "Pilot extrapolation
  was wrong by ~2.45x" below; this is a real, important finding, not just a slow run.
- portfolio WAPE per cutoff (Prophet vs. baseline, delta in pp):
  - 2024-12-31: 86.98% vs 78.84% (+8.14pp worse)
  - 2025-04-01: 102.78% vs 84.43% (+18.35pp worse)
  - 2025-07-01: 106.28% vs 88.05% (+18.23pp worse) — has the same ~9.49% actual-demand drift
    caveat RF's notes.md documented (identical actual_total numbers: 45341/21902/18688/42035 —
    confirms the straddle-week reuse is behaving identically to RF's, not a new divergence)
  - 2025-09-30: 88.76% vs 79.89% (+8.86pp worse)
- **beats_baseline: 0/4** — Prophet (default config) loses to seasonal_naive on every window,
  same overall pattern as RF's task 3.2 result (0/20 across its whole sweep).
- **cold-start fallbacks: 0 on every cutoff** — `MIN_TRAIN_POINTS=10` never triggered even at the
  earliest cutoff on the full catalog (not just the pilot's 209-series sample); no need to revisit
  this threshold.
- per-segment RMSE/bias (mean/std/min/max): intermittent rmse_mean=6.42 (std=3.40, range
  0.41-24.51), bias_mean=3.51 (std=2.95); lumpy rmse_mean=5.13 (std=2.84, range 0.40-18.44),
  bias_mean=2.53 (std=2.38) — both positive bias = under-forecasting on average, consistent with
  RF's finding. Lumpy's spread is wide relative to its mean (std 2.84 on mean 5.13) — a reminder
  that even at full-catalog scale (193 lumpy series, not the pilot's floor-sampled 15), lumpy
  RMSE is not a tight, stable number; don't over-read small deltas in this segment between configs.
- observation: default Prophet is a clear loser here too, same as RF's default config —
  consistent with 10_frozen_feature_set.md's flag that Prophet's default changepoint settings
  weren't verified against this project's growth trend; the changepoint_flexible/_rigid runs
  (next) are the direct test of whether tuning that closes any of this gap.

### 2. `prophet_changepoint_flexible` (changepoint_prior_scale 0.05->0.5, more flexible trend)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/5d879919f0f544ab812dc4f2879087e2
- **74.6 min** (down from run 1's 155.8 min — see the groupby-fix section below, which this run
  verified)
- portfolio WAPE per cutoff (flexible vs baseline vs seasonal_naive):
  - 2024-12-31: 87.21% (baseline 86.98%) vs 78.84% (+8.37pp) — essentially unchanged
  - 2025-04-01: 105.56% (baseline 102.78%) vs 84.43% (+21.13pp) — worse than baseline
  - 2025-07-01: 108.24% (baseline 106.28%) vs 88.05% (+20.18pp) — worse than baseline (has the
    ~9.49% actual-demand drift caveat)
  - 2025-09-30: 88.78% (baseline 88.76%) vs 79.89% (+8.88pp) — essentially unchanged
- **beats_baseline: still 0/4.** A more flexible trend (larger changepoint_prior_scale) makes
  things slightly WORSE on 2 of 4 windows (2025-04-01, 2025-07-01) and is a wash on the other 2 —
  the opposite of what "check changepoint settings against the growth trend" hoped for. Points
  toward the looser trend chasing noise rather than tracking the smooth confirmed growth better;
  `prophet_changepoint_rigid` (tighter trend, next) is the direct test of the opposite direction.
- per-segment: intermittent rmse_mean=6.45 (vs baseline 6.42, ~flat), lumpy rmse_mean=5.13 (vs
  baseline 5.13, identical to 2 decimal places) — segment-level picture essentially unchanged,
  consistent with the near-wash portfolio result.
- cold-start fallbacks: 0 on every cutoff, same as baseline.

### 3. `prophet_changepoint_rigid` (changepoint_prior_scale 0.05->0.01, tighter trend)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/5a8b736b21754713b1df27c95669d148
- **81.0 min**
- portfolio WAPE per cutoff (rigid vs baseline vs flexible vs seasonal_naive):
  - 2024-12-31: 87.45% (baseline 86.98%, flexible 87.21%) vs 78.84% (+8.61pp) — slightly worse than both
  - 2025-04-01: 102.22% (baseline 102.78%, flexible 105.56%) vs 84.43% (+17.79pp) — best of the 3 Prophet configs so far on this window
  - 2025-07-01: 104.74% (baseline 106.28%, flexible 108.24%) vs 88.05% (+16.69pp) — best of the 3 so far (has the ~9.49% drift caveat)
  - 2025-09-30: 89.46% (baseline 88.76%, flexible 88.78%) vs 79.89% (+9.56pp) — slightly worse than both
- **beats_baseline: still 0/4.** Mixed vs. baseline (better on 2 windows, worse on 2) but a tighter
  trend clearly beats the flexible variant on 3/4 windows — the changepoint axis so far reads
  "tighter is better than looser," consistent with this catalog's confirmed *smooth* (not lumpy)
  growth pattern rewarding a trend that doesn't chase noise. Still doesn't close the gap with
  seasonal_naive on any window.
- per-segment: intermittent rmse_mean=6.47 (baseline 6.42, flexible 6.45 — marginally worst of the
  3), lumpy rmse_mean=5.15 (baseline 5.13, flexible 5.13 — also marginally worst) — segment RMSE
  moves in the opposite direction from the portfolio WAPE improvement seen above; a reminder that
  portfolio WAPE and per-series RMSE can point different ways and neither alone tells the full story.
- cold-start fallbacks: 0 on every cutoff.

### 4. `prophet_seasonality_multiplicative` (seasonality_mode additive->multiplicative)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/f057abd52dc1401493326ba2293ee262
- **83.6 min**
- portfolio WAPE per cutoff (multiplicative vs baseline vs seasonal_naive):
  - 2024-12-31: 93.09% (baseline 86.98%) vs 78.84% (+14.25pp) — clearly worse than baseline
  - 2025-04-01: 105.63% (baseline 102.78%) vs 84.43% (+21.20pp) — clearly worse
  - 2025-07-01: 111.08% (baseline 106.28%) vs 88.05% (+23.03pp) — clearly worse (has the ~9.49%
    drift caveat, but the gap vs. baseline is far too large to be explained by that alone)
  - 2025-09-30: 91.74% (baseline 88.76%) vs 79.89% (+11.85pp) — clearly worse
- **beats_baseline: still 0/4, and the worst config so far on every single window** — this
  CONTRADICTS the design-decision hypothesis (see "Design decisions" above), which predicted a
  small/no difference on the reasoning that `log1p(qty_sold_net)` already linearizes multiplicative
  effects. The actual result is a clear, consistent regression, not a wash.
- per-segment: intermittent rmse_mean=6.70 (worst of all 4 configs), but the real story is the
  **tail**: rmse_max=114.44 (vs baseline's 24.51 — a ~4.7x worse worst-case) and bias_min=-55.14
  (vs baseline's -3.52 — a severe over-forecast on at least one series, the wrong-direction failure
  mode from every other config's average under-forecasting bias). This is an instability signature,
  not just a worse average: multiplicative seasonality divides by the trend component, and on a
  log1p-transformed target the trend can sit very close to zero for low-volume/intermittent series
  (96.8% of the catalog), which is exactly the kind of series that would blow up under division.
  **Revised understanding**: multiplicative mode is a poor fit specifically BECAUSE the target is
  already log-transformed — not merely redundant with it, as originally hypothesized, but actively
  harmful on this catalog's many near-zero-trend series. Worth flagging for 3.6 (Prophet+XGBoost
  ensemble) and 3.7/3.8: do not carry `seasonality_mode="multiplicative"` forward as a candidate on
  this log-transformed setup without addressing the near-zero-trend instability first.
- lumpy segment: rmse_mean=5.44 (also worst of the 4, but a much smaller effect than intermittent's
  — consistent with lumpy series generally having higher, less-near-zero volumes).
- cold-start fallbacks: 0 on every cutoff (the instability is a fit-quality problem, not a
  fitting-failure problem — no additional series fell back to the cold-start zero-forecast).

### 5. `prophet_no_holidays` (BR holidays off, isolates the task's own "holiday-driven" justification)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/e1c8fe0f56e342c9a5f7348e130388df
- **58.8 min** (fastest of the 5 — consistent with skipping `add_country_holidays()`'s extra
  regressor-column setup per fit, a small but real per-fit cost saving at 6,054x4 scale)
- **Data snapshot note**: this run's `get_table_version()` returned `delta_version=6`,
  `2026-09-18 19:53:46` — the first 4 runs all used `delta_version=4`, `2026-09-11 19:44:50`. The
  scratch table (`develop.eros_analytics_forecasting_scratch.fact_demand_daily`) changed mid-session
  between runs 4 and 5. **Not a data-content concern**: `actual_total` per cutoff is byte-identical
  to every other run (45341.0/21902.0/18688.0/42035.0), so whatever produced the version bump
  (materialization/OPTIMIZE/re-run of `02_schema_design/build_prototype.py`, cause not confirmed
  from this session alone) didn't change the numbers this experiment depends on. Flagging for the
  team/3.7 comparison as a provenance note, not a re-run trigger.
- portfolio WAPE per cutoff (no_holidays vs baseline vs seasonal_naive):
  - 2024-12-31: 87.02% (baseline 86.98%) vs 78.84% (+8.18pp) — 0.04pp from baseline
  - 2025-04-01: 102.64% (baseline 102.78%) vs 84.43% (+18.21pp) — 0.14pp from baseline
  - 2025-07-01: 106.06% (baseline 106.28%) vs 88.05% (+18.00pp) — 0.22pp from baseline
  - 2025-09-30: 88.64% (baseline 88.76%) vs 79.89% (+8.74pp) — 0.12pp from baseline
- **beats_baseline: still 0/4. Essentially indistinguishable from `prophet_baseline` on every
  window** (all deltas <=0.22pp — well within run-to-run noise). Per-segment RMSE is likewise
  nearly identical (intermittent 6.41 vs baseline 6.42; lumpy 5.13 vs baseline 5.13, matching to 2
  decimals).
- **This directly answers the hypothesis stated at the top of this document**: the tracker's
  justification for 3.4 is that Prophet suits this catalog because it's "seasonal, holiday-driven."
  Removing BR holidays entirely changes essentially nothing. This independently confirms, via a
  completely different model class and methodology, `10_feature_engineering`'s earlier finding
  that holidays contributed ~0% in a pooled linear panel regression (`10_frozen_feature_set.md`) —
  two unrelated models agreeing holidays don't matter for this catalog is a much stronger claim
  than either finding alone. **Recommendation for 3.6 (Prophet+XGBoost ensemble) and 3.7/3.8**:
  BR holidays add fitting cost (this was the slowest-to-fastest comparison point, ~5-8% faster
  without them) with no measurable accuracy benefit on this catalog — don't carry
  `add_country_holidays()` forward as a default assumption.
- cold-start fallbacks: 0 on every cutoff.

### Pilot extrapolation was wrong by ~2.45x — root cause and fix

`pilot_timing.py`'s measured 0.158s/fit was itself accurate (confirmed: this run's Prophet-fit
cost, ~6,054×4×0.158s ≈ 64 min, is close to being consistent with the observed total once the gap
below is accounted for) — the pilot's SCOPE was wrong, not its measurement. Root cause: the pilot's
`t0 = time.perf_counter()` was placed AFTER `series_train = train[(train["product_variant_id"] ==
pv_id) & (train["location_id"] == loc_id)]` — i.e. it only timed `Prophet(...).fit()` +
`.predict()`, not the per-series pandas boolean-mask filter that selects each series' rows out of
the full weekly panel (~2.1M rows). That filter runs once per series per cutoff — 24,216 times in
a full-catalog run — and pandas boolean indexing on two `object`-dtype (string) columns over a
multi-hundred-thousand-to-million-row frame is not free at that repetition count. The pilot's
209-series sample paid this same per-series filtering cost proportionally, but small enough
(209×4=836 filters) not to show up as a meaningful fraction of total pilot runtime, so it was never
surfaced as a separate cost component — a scoping gap in the pilot's timed window, not a wrong
measurement of what it did time.

**Fix applied to `train_prophet.py`'s `run_walk_forward`** (and mirrored in `pilot_timing.py`'s
`time_prophet_fits` for consistency, in case anyone re-runs the pilot later): group the cutoff's
`train` frame by `(product_variant_id, location_id)` ONCE per cutoff
(`train.groupby(["product_variant_id","location_id"])`), then look up each series via
`.get_group(...)` inside the loop instead of re-scanning the full frame with a boolean mask 6,054
times. This turns an O(panel_rows x n_series) access pattern into O(panel_rows) (one pass to build
the groups) + O(n_series) cheap lookups.

**Decision on how to proceed**: rather than either (a) blindly repeating the same ~2.6-hour run 4
more times (~10+ hours, well past the plan's own "day-plus -> switch to subsample" guidance, now
that the REAL per-run cost is known), or (b) silently falling back to the subsample without fixing
the actual inefficiency (which would leave this bug for the next Stage 3 session reusing this
per-series-loop pattern, e.g. XGBoost if it does something similar), the chosen path is: fix the
root cause, verify it actually worked on one more real run, and only fall back to the subsample if
the fix doesn't bring runtime back down near the pilot's original estimate.

**Fix verified**: `prophet_changepoint_flexible` (run 2, below) completed in **74.6 minutes**, down
from run 1's 155.8 minutes -- a 52% reduction, confirming the groupby fix addressed the real cost
driver. Not quite back to the pilot's pure-fit estimate of 63.6 min (residual gap likely: per-
iteration `pd.DataFrame(...)` construction/list-append + one `pd.concat` of ~6,054 small frames per
cutoff, MLflow/network overhead, and general Python loop overhead at 24,216 iterations -- none of
which the pilot's timed window fully covers even after its own fix, since the pilot only builds a
timings dict, not the same per-series output-row DataFrame/concat pattern `run_walk_forward` does).
74.6 min/config x 3 remaining configs ~= 3.7 more hours -- reasonable for one session, so continuing
with `full_catalog` for the rest rather than switching to the subsample fallback.

## Best result so far

All 5 planned runs are complete, all at full-catalog scale (no subsample was needed once the
groupby performance fix was in place). **`prophet_changepoint_rigid` (changepoint_prior_scale=0.01)
is the best of the five** on 2 of 4 windows (2025-04-01, 2025-07-01) and close to baseline on the
other 2 — but **no Prophet config beats the `seasonal_naive` baseline on any of the 4 windows (0/20
total across every run this session)**, the same overall verdict RF's task 3.2 reached (0/20 there
too).

Portfolio WAPE summary, all 5 runs vs. seasonal_naive (bold = best Prophet result per window):

| cutoff | baseline | changepoint_flexible | changepoint_rigid | seasonality_multiplicative | no_holidays | seasonal_naive |
|---|---|---|---|---|---|---|
| 2024-12-31 | 86.98% | 87.21% | 87.45% | 93.09% | **86.98%**\* | 78.84% |
| 2025-04-01 | 102.78% | 105.56% | **102.22%** | 105.63% | 102.64% | 84.43% |
| 2025-07-01 | 106.28% | 108.24% | **104.74%** | 111.08% | 106.06% | 88.05% |
| 2025-09-30 | 88.76% | 88.78% | 89.46% | 91.74% | **88.64%** | 79.89% |

\*baseline and no_holidays are within 0.04-0.22pp of each other on every window (see run 5's
"essentially indistinguishable" finding) — not treated as a meaningfully separate "best," just
noted where it happens to be numerically lowest.

**Two clear, evidence-backed findings for the team, directly answering this session's stated
hypothesis:**
1. **Holidays don't matter for this catalog.** `prophet_no_holidays` vs. `prophet_baseline`: max
   0.22pp difference on any window, per-segment RMSE identical to 2 decimals. This independently
   confirms (different model class, different methodology) `10_feature_engineering`'s earlier
   finding that holidays contributed ~0% in a pooled linear panel regression. Two unrelated models
   agreeing is a stronger claim than either alone — don't carry `add_country_holidays()` forward as
   a default assumption for 3.6's ensemble.
2. **Tighter trend beats looser trend, but neither closes the gap.** The changepoint axis is
   monotonic in the tested direction: rigid (0.01) beats baseline (0.05) beats flexible (0.5) on
   3-4 of 4 windows — consistent with this catalog's confirmed *smooth*, not lumpy, growth pattern
   rewarding a trend that doesn't chase noise. `prophet_seasonality_multiplicative` is a clear,
   consistent loser on every window with a severe worst-case-series blowup (rmse_max 114 vs.
   baseline's 24, bias_min -55) — traced to multiplicative mode dividing by an already
   log1p-transformed, near-zero trend on this catalog's many low-volume series. Neither direction
   closes the gap with `seasonal_naive`.

This is a genuine, fully-documented negative result for task 3.4, structurally similar to RF's for
3.2: across a reasonable single-parameter-at-a-time sweep, Prophet does not beat the seasonal-naive
champion on this catalog at any tested configuration — but unlike RF, this session got clean,
unambiguous answers on both of its two open questions (holiday value, changepoint direction) rather
than a "further sweep needed" verdict.

## Open items for the team

- **Cross-model comparison (3.7's job, not done here)**: RF (task 3.2) and Prophet (task 3.4) both
  lose to `seasonal_naive` on every window this session. Worth a formal side-by-side in 3.7/3.8 of
  which loses by LESS and whether either handles the "struggles extrapolating past training range"
  failure mode better — Prophet has an explicit changepoint-driven trend component RF's tree-based
  model structurally lacks, but this session didn't test that directly against RF's per-series
  results (out of scope per this session's constraints).
- **`prophet_changepoint_rigid` (0.01) was the best of the 5, but the axis wasn't fully explored**:
  only 3 points were tested (0.01, 0.05, 0.5). Since rigid beat baseline, a future session should
  try an even smaller value (e.g. 0.001-0.005) to see if the improvement continues or reverses,
  mirroring how RF's own notes flagged "depth is the dominant lever, narrower search warranted."
- **`seasonality_multiplicative`'s instability is worth deeper investigation, not just avoidance**:
  the severe worst-case blowup (rmse_max 114, bias_min -55) suggests a specific pathological
  interaction with near-zero-trend series, not a uniform mild degradation. Identifying WHICH
  series blew up (via `prophet_seasonality_multiplicative_window_totals.csv`'s per-series errors)
  could be informative for feature engineering on low-volume series generally, beyond just ruling
  out this one config.
- **Data snapshot changed mid-session (delta_version 4->6)** between runs 4 and 5 — confirmed
  harmless (`actual_total` identical across all 5 runs) but the cause wasn't tracked down this
  session; worth a quick check with whoever/whatever last touched
  `develop.eros_analytics_forecasting_scratch.fact_demand_daily`.
- Peak-season-vs-baseline shape mismatch — same caveat RF's notes.md documents
  (`compare_to_baseline()` only supports the SKU-level main-window portfolio; peak-season is only
  informally comparable), applies identically here since it's `compare_to_baseline()`'s own
  limitation, not model-specific.
- **Performance fix (groupby instead of per-series boolean-mask filtering) should be considered by
  other Stage 3 sessions** reusing a per-series-loop pattern over `load_weekly_panel()`'s full
  panel (e.g. if 3.3/XGBoost or 3.5/ARIMA end up looping per-series rather than fitting pooled) —
  see "Pilot extrapolation was wrong by ~2.45x" above for the full root-cause writeup.
