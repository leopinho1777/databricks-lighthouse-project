# Hierarchical Reconciliation — Stage 4: MinT Feasibility Check

Validates whether MinT (Minimum Trace) reconciliation is applicable to this
catalog *before* attempting it, per the reconciliation context document's
Section 3 feasibility gate. Produced by
[`../run_stage4_mint_feasibility.py`](../run_stage4_mint_feasibility.py);
period-sufficiency numbers in
[`period_sufficiency_check.csv`](period_sufficiency_check.csv), covariance
stability numbers in
[`covariance_stability_check.csv`](covariance_stability_check.csv).

## Verdict: **Not feasible**, at either hierarchy level, by a wide margin.

Both feasibility checks below fail decisively at both the national (1,009
products) and location (6,054 product×location series) level. Per the
context document's own instruction, this stage stops here rather than
forcing a MinT implementation on an unstable covariance estimate.

## Method

- **Base forecasts** (feasibility check 2): Stage 1's Bottom-Up (via `06`'s
  recommended per-series forecast) and Stage 2's Top-Down (national SBA fit)
  — both already validated in Stages 1-3. This check **passes**; it's the
  other two that fail.
- **Error matrices**: for each level, a (holdout day × series) matrix of
  `actual - forecast`, built directly from Stage 1's/`06`'s and Stage 2's
  already-cached forecasts (no new forecasting logic) — 365 holdout days ×
  1,009 national series, and 365 × 6,054 location series.
- **Check 1 (period sufficiency)**: holdout observation count vs. the
  reconciliation plan's rule-of-thumb requirement of 3-5x the number of
  series being reconciled at that level.
- **Check 3 (covariance stability)**: rather than forming the full
  (n_series × n_series) sample covariance matrix directly — 6,054² ≈ 293MB,
  plus an expensive full SVD for the condition number — its nonzero
  eigenvalues are exactly the squared singular values of the much cheaper
  (n_obs × n_series) error matrix (a standard identity: a sample covariance
  matrix from `n_obs` observations has rank at most `n_obs - 1`, regardless
  of `n_series`). Computed via `numpy.linalg.svd` on the de-meaned error
  matrix directly — no `scipy` needed, per `pyproject.toml`'s `forecasting`
  group only listing `numpy`/`pandas`/`databricks-sql-connector`.

## Results — Check 1: holdout period sufficiency

| level | n_series | holdout obs | required (3x-5x) | actual/required (3x) | sufficient? |
|---|---|---|---|---|---|
| national | 1,009 | 365 | 3,027 - 5,045 | **12.1%** | **No** |
| location | 6,054 | 365 | 18,162 - 30,270 | **2.0%** | **No** |

The catalog has **one year** of usable daily holdout history. The
rule-of-thumb requirement is measured in years-equivalent multiples of the
series count — at location grain, reaching even the 3x floor would require
**~50-83x as much holdout data as exists today** (an additional ~48.8-81.9
years of daily history at the current per-series count, on top of the one
year already in hand). This is not a marginal
shortfall to recalibrate the rule-of-thumb around — it's off by more than an
order of magnitude at both levels, and by nearly two at location level.

## Results — Check 3: covariance numerical stability

| level | n_series | n_obs | max possible rank | effective rank | zero eigenvalues | % series with zero eigenvalue | cond. number (among nonzero) | stable? |
|---|---|---|---|---|---|---|---|---|
| national | 1,009 | 365 | 364 | 364 | 645 | **63.9%** | 99.0 | **No** |
| location | 6,054 | 365 | 364 | 364 | 5,690 | **94.0%** | 24.0 | **No** |

Both levels hit the analytically-predicted rank ceiling *exactly*
(`effective_rank == n_obs - 1 == 364` in both cases) — this isn't
approximate numerical noise, it's the mathematical consequence of estimating
a covariance matrix from fewer observations than series. At the location
level, **94% of the covariance matrix's eigen-directions are exactly zero**
— the matrix is not merely ill-conditioned, it is **exactly singular** and
cannot be inverted at all, which the MinT reconciliation formula requires.
The "condition number" columns above describe only the spread *among the
364 surviving nonzero eigenvalues* — informational, not a measure of overall
stability, since the true condition number of an exactly-singular matrix is
infinite, not 99.0 or 24.0.

## What would need to change for MinT to become viable

- **More holdout history is the direct fix but is not realistic soon**:
  reaching the 3x-5x range needs ~7.3-12.8 more years of daily history at
  national grain, ~48.8-81.9 more years at location grain. Location grain's
  requirement is fundamentally out of reach for a catalog this granular —
  even with a decade more data, it would still fall short of the low end of
  the rule-of-thumb range.
- **A more realistic path: a shrinkage or diagonal covariance estimator**,
  not more data. The MinT literature (Wickramasuriya, Athanasopoulos &
  Hyndman, 2019) anticipates exactly this n_series >> n_obs regime and
  offers variants — shrinkage estimators (e.g., Schäfer-Strimmer-style
  shrinkage toward a diagonal target) or the simpler WLS variant (using only
  per-series forecast error *variances*, never the full off-diagonal
  covariance structure) — that sidestep needing to invert a rank-deficient
  full covariance matrix at all. This feasibility check specifically tested
  the full-sample-covariance approach (the most direct reading of the
  reconciliation context document's Section 2.3 description); a shrinkage or
  diagonal variant remains a legitimate, lower-data-requirement option for a
  future phase and is not ruled out by this result — it just wasn't what was
  gated here, and would be a different (smaller) scope of work than "MinT as
  originally scoped."

## Recommendation

Per the reconciliation plan's own instruction for this outcome: **do not
implement MinT.** Proceed with the better of Top-Down/Bottom-Up from Stage
3 instead — which Stage 3 found to be **Bottom-Up**, winning decisively at
national level (80.4% of products, portfolio RMSE 3.7% lower) and tying at
location level (59.8%/40.2%, pooled RMSE identical to 4 decimals).

## Checkpoint

This closes the staged execution plan (Stages 1-4). See the final
deliverable summary for how this ties back to the classification finding
that motivated the whole workstream.
