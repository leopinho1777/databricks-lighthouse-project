# Random Forest (task 3.2) — running notes

Working log, not a polished report. Status: all 5 planned MLflow runs executed against the
live workspace and logged under `/Shared/02_model_comparison`, results recorded below.
Bottom line: no config beats `seasonal_naive` on any window (0/20) -- see "Best result so
far" for the full comparison table and "Open items" for concrete follow-ups (entity-code
drop, finer depth sweep).

## Hypothesis being tested this session

One RF fit across the whole catalog (~6,054 series), no explicit Smooth/Intermittent/Lumpy
segment label as a model input — deliberate, not an oversight. `04_demand_classification`
found 96.8% Intermittent / 3.2% Lumpy (no Smooth/Erratic series at this grain), and
`05_croston_sba` routed the whole catalog to a segment-aware method on the strength of that
split. This run tests whether `entity_mean_log_qty x month_*` tree splits can implicitly
approximate that segmentation instead of needing an explicit label — a genuine test of "can
one flexible model substitute for explicit segmentation," not an assumption that
segmentation doesn't matter. Answered per run via the post-hoc per-segment RMSE/bias join
(`demand_classification.csv`) logged as `{run_name}_segment_summary.csv`, not just asserted
— so the later 3.7/3.8 cross-model comparison can weigh "best segmented approach" vs. "best
single flexible model" as genuinely different strategies rather than assuming equivalence.

## Design decisions (written before any runs)

- **Entity identity**: `entity_mean_log_qty` (mean-log-qty encoding, the practical analogue
  of `PanelOLS(entity_effects=True)`'s absorbed fixed effect) + `product_variant_id_code` /
  `location_id_code` (integer codes, for entity x season interactions a fixed-effect
  intercept can't represent). **Predetermined response** if the codes dominate feature
  importance (exceed `entity_mean_log_qty` + all `month_*` combined): drop the raw codes in
  a follow-up run, keep `entity_mean_log_qty` alone — not re-litigated mid-analysis, since
  ~1,009 arbitrary product IDs carry no real ordering and risk spurious splits.
- **Frozen calendar feature** = `month_2`..`month_12` only. The Fourier-terms question is
  already resolved centrally, not re-decided here: `10_frozen_feature_set.md` (lines
  26-29/58-59) explicitly states both `week_of_year_sin`/`week_of_year_cos` are dropped from
  the production feature set, settled by a direct holdout ablation (task 2.9's VIF-44
  collinearity finding cited only as supporting explanation).
- **Target**: `log1p(qty_sold_net)`, back-transformed via `expm1().clip(lower=0)`, matching
  the Stage 2 convention.
- **No recursive multi-step forecasting**: `month_*`/`trend` are known in advance for any
  future week, so one `model.predict()` call covers all 13 horizon weeks per cutoff.
- **Known limitation, documented not worked around**: RF trees can't extrapolate `trend`
  past their training range. For later cutoffs (esp. 2025-09-30) this flattens the model's
  response to continued growth — exactly the "struggles predicting values higher than
  anything seen historically" risk the tracker names for this task. Expect growing negative
  bias toward later cutoffs; check this against actual results below, don't try to fix it
  here (out of scope for 3.2).
- **Leak-safety fix found during implementation**: the protocol's 4 cutoffs are all
  Tuesdays (91 = 13×7, so the weekday never shifts), so no week's Monday-anchor lines up
  with a cutoff — naively filtering `train = panel[period <= cutoff]` at weekly grain would
  silently pull a few future days into the last training week. Fixed by excluding the
  straddling week from both train (`period <= cutoff - 6 days`) and the scored horizon
  (`period` starts at the first Monday *strictly after* cutoff) — costs a handful of days
  at each boundary relative to the baseline's exact 91-day daily-grain window, an accepted
  approximation of weekly bucketing, not a leakage bug. See `train_random_forest.py`'s
  `run_walk_forward` docstring/comments.
- **Peak months** fixed once from data `<= 2024-12-31` (matches `run_genuine_baseline.py`'s
  actual approach — a single value reused across all 4 cutoffs there), not recomputed per
  cutoff.
- **`compare_to_baseline()` peak-season caveat**: it only supports the SKU-level main-window
  portfolio (`load_baseline_portfolio()` reads a CSV with no peak-season variant in that
  shape). Main-window is compared via `compare_to_baseline()` per the protocol; peak-season
  metrics are logged (`peak_rmse_mean`, `peak_bias_mean`) but only informally comparable
  against `09_baseline_close_out/output/genuine_baseline_metrics_peak_season.csv`'s
  `seasonal_naive` row (`rmse`/`bias` only, no `wape_pct`, no per-cutoff breakdown) — not
  forced into a false `beats_baseline` boolean.
- **Reproducibility helper centralized**: `get_table_version()` / `get_library_versions()`
  now live in `forecasting/experiments/_shared/repro.py` (new, this session) rather than
  inline in this script — first Stage 3 session, so this is the shared pattern for
  `eros_xgboost`/etc. to reuse as-is rather than reimplementing per person.
- Data snapshot: delta_version=`4`, delta_timestamp=`2026-09-11 19:44:50+00:00`.
  Library versions: sklearn=`1.9.1`, pandas=`2.3.3`, numpy=`1.26.4`, mlflow=`3.16.0`.

## Bugs found and fixed while actually executing against the live workspace

Static verification (ruff, offline synthetic smoke tests) didn't catch these — they only
surfaced once real runs were attempted against the real workspace:

1. **`ndarray.clip(lower=0)` → `TypeError`**: `model.predict()` returns a numpy array, not a
   pandas Series. `ndarray.clip()` takes `min=`/`max=`, not pandas' `lower=`/`upper=`. Fixed
   to `.clip(min=0)`. Caught after a full ~10-minute real fit on cutoff 1 completed and the
   prediction step crashed — costly to hit, so added an offline dry-run (tiny synthetic RF fit
   exercising the exact `predict -> expm1 -> clip` path) before every subsequent re-run.
2. **`mlflow.sklearn.log_model()` → `ModuleNotFoundError: No module named 'skops'`**: this
   mlflow version (3.16.0, via `mlflow-skinny`) defaults sklearn model serialization to
   `"skops"`, which isn't a project dependency. Fixed by passing
   `serialization_format="cloudpickle"` explicitly (already available transitively via
   mlflow) rather than adding a new top-level dependency for this.
3. **`get_library_versions(["mlflow"])` → `PackageNotFoundError`**: this project depends on
   the `mlflow-skinny` distribution, not `mlflow` — `import mlflow` and `mlflow.__version__`
   work fine, but `importlib.metadata.version("mlflow")` has no matching distribution record.
   Fixed in `repro.py` with a fallback chain: exact name → `<name>-skinny` → import the module
   and read `__version__`.

## Actual-demand drift vs. the baseline — measured and explained, not a bug

The first real `random_forest_baseline` run triggered `compare_to_baseline()`'s drift warning:
*"actual demand differs from the baseline by up to 9.49%"*. Investigated directly against the
live warehouse rather than left as an unexplained warning:

| cutoff | our actual_total | baseline actual_total | drift |
|---|---|---|---|
| 2024-12-31 | 45,341 | 45,909 | -1.24% |
| 2025-04-01 | 21,902 | 23,007 | -4.80% |
| 2025-07-01 | 18,688 | 17,069 | **+9.49%** |
| 2025-09-30 | 42,035 | 40,968 | +2.60% |

Decomposed the 2024-12-31 and 2025-07-01 windows into two independent effects (isolated via
direct SQL against `fct_sales`/`fact_demand_daily`, holding one factor fixed at a time):
- **qty-definition effect** (`fact_demand_daily`'s net `qty_sold_net` vs. `fct_sales`'s gross
  `quantity`, same date range): consistently small, -0.65% to -0.67% on both windows tested.
- **window-shift effect** (same net qty definition, baseline's exact date range vs. our
  straddle-week-shifted range): -0.59% on the Dec-31 window, but **+8.41%** on the Jul-1
  window — the dominant driver of that cutoff's 9.49% total drift.

Conclusion: this is a real, structural consequence of the leak-safe straddle-week exclusion
(see Design decisions above) — our horizon starts ~5 days later than the baseline's exact
cutoff+1 boundary, and early October (which we include, baseline doesn't) apparently carries
meaningfully higher demand than early July (which baseline includes, we don't) in this data —
not a bug in the aggregation or a qty-definition mismatch (that part stays small and
consistent everywhere it was checked). `evaluate.py`'s own docstring explicitly permits
weekly-grain models ("free to fit at whatever grain suits it... sums into the window"), and
`compare_to_baseline()` only warns rather than blocking, for exactly this kind of grain-vs-
exact-window mismatch. Treat the 2025-07-01 window's WAPE/`beats_baseline` result with reduced
confidence relative to the other three; do not silently treat it as equally comparable.

## Runs (in order)

### 1. `random_forest_baseline` (n_estimators=300, max_depth=None, min_samples_leaf=1, max_features=1.0)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/6d7fc7187794476780c08dd38971c0bd
- portfolio WAPE per cutoff (RF vs. baseline, delta in pp):
  - 2024-12-31: 99.37% vs 78.84% (+20.53pp worse)
  - 2025-04-01: 165.25% vs 84.43% (+80.82pp worse) -- standout bad window
  - 2025-07-01: 110.46% vs 88.05% (+22.40pp worse) -- has the ~9.49% actual-demand drift
    caveat above; treat with reduced confidence, though the other 3 windows also lose badly
    so this isn't purely a window-mismatch artifact
  - 2025-09-30: 97.72% vs 79.89% (+17.82pp worse)
- **beats_baseline: 0/4 cutoffs** -- RF (default config) loses to seasonal_naive in every window
- per-segment RMSE/bias (hypothesis check): intermittent rmse=7.86/bias=2.63,
  lumpy rmse=6.29/bias=1.72 (both positive bias = under-forecasting on average)
- top features by mean importance: trend=37.4%, entity_mean_log_qty=26.4%,
  product_variant_id_code=24.7%, location_id_code=6.8%, all month_* combined ~4.7%
  (each individually ~0.1-1.1%)
- **entity-code predetermined-response check**: codes combined (31.5%) vs.
  entity_mean_log_qty+months (31.1%) -- borderline, too close to call "dominates"
  under the predetermined rule. Not dropping the codes yet; re-check once a bounded-depth
  config's importances are in, since unbounded trees may be spreading importance across the
  raw codes for reasons a depth cap would suppress.
- observation: the default RF config is a clear loser here -- worse than the naive baseline
  on every single window, most dramatically on 2025-04-01. `trend` dominating importance
  (37.4%) is consistent with the documented extrapolation-limitation concern (trees can't
  extrapolate past their training range), but the badly-losing 2025-04-01 window doesn't have
  an unusually large actual-demand drift (-4.80%, smaller than 2025-07-01's), so trend
  extrapolation alone likely isn't the whole story -- worth a closer look once the bounded
  configs (which cap the model's ability to overfit into deep, hyper-specific leaves) come in,
  to see whether this is fundamentally an overfitting problem from unbounded depth + leaf=1
  on a heavily zero-inflated (92.9%-zero-per-earlier-classification) catalog.

### 2. `random_forest_depth10` (max_depth None→10 vs. baseline)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/3b77d70a384343b1a70da72821678901
- portfolio WAPE per cutoff (depth10 vs. baseline/unbounded vs. seasonal_naive):
  - 2024-12-31: 87.95% (was 99.37% unbounded) vs 78.84% (+9.11pp worse)
  - 2025-04-01: 107.04% (was 165.25% unbounded) vs 84.43% (+22.61pp worse) -- huge improvement
    over unbounded, though still losing
  - 2025-07-01: 103.96% (was 110.46% unbounded) vs 88.05% (+15.90pp worse) -- has the ~9.49%
    actual-demand drift caveat
  - 2025-09-30: 89.72% (was 97.72% unbounded) vs 79.89% (+9.83pp worse)
- **beats_baseline: still 0/4**, but depth-capping closed a large chunk of the gap on every
  window, most dramatically 2025-04-01 (165%->107% WAPE) -- confirms unbounded trees were
  substantially overfitting, not just extrapolating trend badly
- per-segment RMSE/bias: intermittent rmse=6.44/bias=3.48, lumpy rmse=5.05/bias=2.46 (both
  improved RMSE vs unbounded's 7.86/6.29, but bias grew slightly more positive -- capping
  depth trades some overfit-driven variance for a bit more systematic under-forecasting)
- top features by mean importance: trend=30.8%, entity_mean_log_qty=28.1%, months
  combined=31.2% (month_6/7/8/5/9 now each 4.8-6.7%, much higher than unbounded's ~0.1-1.1%
  each), entity codes combined=9.9% (product_variant_id_code=7.8%, location_id_code=2.1%)
- **entity-code predetermined-response check, resolved**: codes (9.9%) vs.
  entity_mean_log_qty+months (59.3%) -- clearly NOT dominating. The borderline call on the
  unbounded run was an artifact of unbounded depth letting trees memorize per-ID levels via
  the raw codes instead of leaning on the smoother entity_mean_log_qty/month signals; once
  depth is capped, importance redistributes sensibly toward the more generalizable features.
  No action needed -- keep both code features as originally designed.
- observation: capping depth is doing real, substantial work here -- this is the single
  biggest lever tried so far. Still not beating the naive baseline, but the shrinking gap
  (esp. on 2025-04-01) suggests further regularization (leaf20) or interaction with
  max_features may close more of it. Worth trying `random_forest_depth5`/similar even
  shallower in a future session if leaf20 doesn't fully explain the remaining gap.

### 3. `random_forest_depth20` (max_depth 10→20, second point on the depth axis)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/d0a0a370ae1d4386b0f2b47c93090e7a
- portfolio WAPE per cutoff (depth20 vs depth10 vs seasonal_naive):
  - 2024-12-31: 87.34% (depth10: 87.95%) vs 78.84% (+8.49pp) -- marginally better than depth10
  - 2025-04-01: 125.42% (depth10: 107.04%) vs 84.43% (+40.99pp) -- notably worse than depth10,
    overfitting creeping back in on this already-volatile window
  - 2025-07-01: 105.89% (depth10: 103.96%) vs 88.05% (+17.84pp) -- slightly worse than depth10
  - 2025-09-30: 91.49% (depth10: 89.72%) vs 79.89% (+11.59pp) -- slightly worse than depth10
- **beats_baseline: still 0/4.** Depth20 is worse than depth10 on 3/4 windows, dramatically so
  on 2025-04-01, though still far better than unbounded everywhere.
- per-segment RMSE/bias: intermittent rmse=6.72/bias=3.26, lumpy rmse=5.45/bias=2.17
  (between depth10's and unbounded's numbers on both counts)
- top features by mean importance: trend=35.8%, entity_mean_log_qty=28.2%, entity codes
  combined=30.6% (product_variant_id_code=24.3%, location_id_code=6.3% -- nearly back to
  unbounded's 31.5%), months combined=only 5.4% (down sharply from depth10's 31.2%)
- observation: **depth10 looks like the sweet spot found so far.** Going from depth 10->20
  reverses much of depth10's generalization gain -- importance shifts back toward raw entity
  ID codes (memorization) and away from months (the more generalizable seasonal signal),
  mirroring the unbounded run's pattern almost exactly. This is a coherent, consistent story
  across all 3 runs so far: shallower trees are forced to rely on smooth/generalizable
  features (entity_mean_log_qty, month_*), deeper trees increasingly memorize via the raw,
  unordered ID codes -- exactly the risk flagged in Design decisions for those code features.
  Confirms depth capping (not leaf-size or max_features, untested yet) is the dominant lever
  so far; worth trying depth5-8 in a future session to see if the sweet spot is even shallower
  than 10.

### 4. `random_forest_leaf20` (min_samples_leaf 1→20, regularizes against the panel's heavy zero-sparsity)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/65d8c8c088b94c47929c1d756992639c
- portfolio WAPE per cutoff (leaf20 vs depth10 vs seasonal_naive):
  - 2024-12-31: 87.02% (depth10: 87.95%) vs 78.84% (+8.18pp) -- essentially matches depth10
  - 2025-04-01: 108.55% (depth10: 107.04%) vs 84.43% (+24.12pp) -- essentially matches depth10
  - 2025-07-01: 104.31% (depth10: 103.96%) vs 88.05% (+16.26pp) -- essentially matches depth10
  - 2025-09-30: 91.07% (depth10: 89.72%) vs 79.89% (+11.17pp) -- essentially matches depth10
- **beats_baseline: still 0/4.** Accuracy is nearly identical to depth10 across all 4 windows
  (within ~1.5pp everywhere) -- but via a genuinely different mechanism, see below.
- per-segment RMSE/bias: intermittent rmse=6.47/bias=3.43, lumpy rmse=5.08/bias=2.39
  (nearly identical to depth10's 6.44/3.48 and 5.05/2.46)
- top features by mean importance: entity_mean_log_qty=35.6%, product_variant_id_code=31.4%,
  trend=18.0%, location_id_code=7.8%, months combined=7.2%. Entity codes combined = 39.1% --
  *higher* than even the unbounded baseline's 31.5%, and nowhere near depth10's suppressed 9.9%.
- **mechanistic finding, not a rule violation**: codes (39.1%) don't exceed
  entity_mean_log_qty+months (42.8%), so the predetermined drop-the-codes response still isn't
  triggered -- but it's worth understanding *why* leaf-size and depth-capping diverge so much
  here despite near-identical final accuracy. Depth=10 caps the tree at 2^10=1024 possible
  leaves, fewer than the ~6,054 distinct (product_variant_id, location_id) entities in the
  panel -- so it is *structurally forced* to share information across entities via
  trend/month/entity_mean rather than memorizing per-entity via the ID codes. min_samples_leaf
  =20 imposes no such structural cap: with ~250 weeks of history per entity in the training
  window, a tree can still carve out near-per-entity leaves while comfortably satisfying the
  20-sample minimum, so it keeps relying on the raw codes much like the unbounded run did.
  That the leaf20 and depth10 configs land on nearly identical WAPE despite this very different
  feature-reliance pattern suggests the codes may carry some genuine per-entity signal beyond
  what entity_mean_log_qty captures (not pure memorization noise) -- worth keeping in mind
  before assuming the codes are dispensable in a future session.

### 5. `random_forest_sqrtfeatures` (max_features 1.0→"sqrt", classic RF decorrelation)
- run: https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/8a91492bc6cc48a491d498376962f847
- portfolio WAPE per cutoff (sqrtfeatures vs depth10/leaf20 vs seasonal_naive):
  - 2024-12-31: 91.04% (depth10 87.95%, leaf20 87.02%) vs 78.84% (+12.20pp)
  - 2025-04-01: 116.19% (depth10 107.04%, leaf20 108.55%) vs 84.43% (+31.76pp)
  - 2025-07-01: 108.62% (depth10 103.96%, leaf20 104.31%) vs 88.05% (+20.57pp)
  - 2025-09-30: 92.16% (depth10 89.72%, leaf20 91.07%) vs 79.89% (+12.26pp)
- **beats_baseline: still 0/4** (0/20 across all 5 configs run this session). Worse than both
  depth10 and leaf20 on every single window, though still clearly better than unbounded
  everywhere. Fastest run of the three regularized configs (~16 min) -- restricting features
  considered per split cuts search cost more than depth/leaf constraints do, but is the least
  effective of the three at closing the baseline gap.
- per-segment RMSE/bias: intermittent rmse=6.78/bias=3.22, lumpy rmse=5.60/bias=2.35
- top features by mean importance: entity_mean_log_qty=36.7%, product_variant_id_code=36.0%,
  trend=23.4%, location_id_code=2.9%, months combined=1.0%
- **entity-code predetermined-response check: TRIGGERED.** Codes combined = 38.88%
  (36.0%+2.9%) vs. entity_mean_log_qty+months = 37.73% (36.7%+1.0%) -- codes marginally
  exceed, by ~1.15pp. Per the rule committed to before any runs (see Design decisions), the
  predetermined response is: drop the raw ID codes, keep entity_mean_log_qty alone, in a
  follow-up run -- not re-litigated here. Flagging as genuinely marginal (~1pp, not a
  landslide) and consistent with the broader pattern across all 5 runs: every config that
  doesn't cap depth (unbounded, leaf20, sqrtfeatures) shows codes at 31-39% importance, while
  the one depth-capped config (depth10) suppresses codes to 9.9%. This reinforces that depth
  capping, not leaf-size or feature-subsampling, is what actually forces the model to
  generalize across entities instead of memorizing via raw IDs -- an open item for the next
  session (see below), not acted on in this one since the 5 planned runs are now complete.

## Best result so far

All 5 planned runs are complete. **`random_forest_depth10` is the best of the five** (lowest
WAPE on 3/4 windows, effectively tied with `leaf20` on all 4) -- but **no RF config beats the
`seasonal_naive` baseline on any of the 4 windows (0/20 total across every run this session)**.

Portfolio WAPE summary, all 5 runs vs. seasonal_naive (bold = best RF result per window):

| cutoff | unbounded | depth10 | depth20 | leaf20 | sqrtfeatures | seasonal_naive |
|---|---|---|---|---|---|---|
| 2024-12-31 | 99.37% | **87.95%** | 87.34%\* | 87.02%\* | 91.04% | 78.84% |
| 2025-04-01 | 165.25% | **107.04%** | 125.42% | 108.55% | 116.19% | 84.43% |
| 2025-07-01 | 110.46% | 103.96% | 105.89% | **104.31%**\*\* | 108.62% | 88.05% |
| 2025-09-30 | 97.72% | **89.72%** | 91.49% | 91.07% | 92.16% | 79.89% |

\*depth20 edges out depth10 by 0.6pp on this one window only; \*\*leaf20/depth10 are within
0.35pp of each other on this window, essentially tied. depth10 is the clear overall winner
once all 4 windows are weighed, especially given its dominant margin on 2025-04-01.

This is a genuine, fully-documented negative result for task 3.2: Random Forest, across a
reasonable single-parameter-at-a-time hyperparameter sweep, does not beat the seasonal-naive
champion on this catalog at any tested configuration. The clearest lever found was depth
capping (not leaf-size, not max_features) -- consistent with the mechanistic finding that
depth=10 structurally forces the model to generalize across the ~6,054-entity catalog rather
than memorize per-entity via the raw ID codes (see run 2/4/5 notes above).

## Open items for the team

- **Entity-code drop, follow-up run needed**: `sqrtfeatures` (and near-miss `leaf20`)
  triggered the predetermined response -- a future session should run a
  `random_forest_depth10_nocode` config (entity codes dropped, `entity_mean_log_qty` kept
  alone) to check whether depth10's already-good result improves further without them, per
  the rule committed to in Design decisions.
- **Depth is the dominant lever, narrower search warranted**: all 3 non-depth-capped configs
  (unbounded, leaf20, sqrtfeatures) show 31-39% importance on the raw entity codes; the one
  depth-capped config (depth10) suppresses that to 9.9% and gets the best accuracy. A future
  session should sweep depth more finely (e.g. 5, 8, 12, 15) rather than leaf-size/max_features,
  since those two knobs moved accuracy far less than depth did this session.
- **Trend-extrapolation limitation**: expected growing negative bias toward later cutoffs
  (RF can't extrapolate past its training range) was the working hypothesis before any runs.
  Actual results don't cleanly confirm this in isolation -- 2025-04-01 (an early-ish cutoff)
  was the worst-performing window in every config, not the latest cutoff (2025-09-30, which
  was consistently one of the *better*-performing windows). Overfitting (see depth-capping
  finding above) appears to be the larger driver this session; trend extrapolation may still
  be a contributing factor but isn't the dominant one based on this evidence.
- **Peak-season vs. baseline comparison shape mismatch**: still only an informal comparison
  (no `beats_baseline`-style boolean); peak metrics were logged every run but not analyzed
  in depth here -- worth a closer look in a follow-up.
- **Actual-demand drift (~9.5% on 2025-07-01 specifically)**: measured, explained, and
  documented above as a structural weekly-grain-bucketing consequence, not a bug -- carry
  this caveat into any 3.7 cross-model comparison that includes this window.
- Entity-code cold-start (`-1`/unmapped codes for entities absent from a given cutoff's
  training window) not exercised/stress-tested this session.
- **Segmentation hypothesis -- partially answered, not fully**: this session's evidence is
  that RF (all 5 configs) loses to the non-segmented `seasonal_naive` baseline in portfolio
  WAPE on every window -- so single-model RF clearly does *not* close the gap with
  `seasonal_naive`. Per-segment RMSE was consistently lower for `lumpy` than `intermittent`
  across all 5 runs (e.g. depth10: 6.44 vs 5.05), but RMSE is not scale-normalized and lumpy
  series may simply have different volume levels than intermittent ones -- this should *not*
  be read as "RF handles lumpy demand better," without checking whether that's a scale
  artifact. Whether RF specifically closes the gap with the *segmented* Croston/SBA approach
  (rather than seasonal_naive) requires comparing this session's per-series RMSE against
  `05_croston_sba`'s own per-series numbers -- that comparison wasn't done this session
  (out of scope per the constraints: cross-model comparison is 3.7's job) and is the real
  input needed to answer the hypothesis posed at the top of this document.
