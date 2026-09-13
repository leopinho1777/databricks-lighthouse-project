# Hierarchical Reconciliation — Final Summary (Stages 1-4)

Ties the four-stage Top-Down / Bottom-Up / MinT comparison back to the
finding that motivated it: `04_demand_classification` found 96.8% of the
6,054 product×location series Intermittent and 0% Smooth, with the lowest
ADI in the entire catalog ~45x the classification threshold — a structural,
not fixable-by-aggregating-time, sparsity problem (`06` confirmed this again
at weekly grain: still 0% Smooth/Erratic even after aggregating 7 days into
1). This workstream tested whether aggregating across *location* instead —
summing to national-level product demand — behaves differently, and if so,
how to reconcile that stronger signal with the location-level detail the
client's own requirements (per-store forecasting, distribution-center
analysis) need.

## What's now validated with real numbers

- **National aggregation does help, modestly, and in a more interesting way
  than expected.** Stage 1/2 found national zero-actual sparsity drops from
  ~99% (per-location, 2025 holdout) to ~94% (national) — real, but nowhere
  near enough to reach Smooth. What *did* change unexpectedly: national-grain
  reclassification (Stage 2) found the **Lumpy segment disappears entirely**
  (3.2%→0%) even though ADI doesn't move — aggregating locations reduces
  sale-size variability (CV²) via a real central-limit effect, while ADI
  stays pinned by the persistent zero-actual rate. Aggregating across time
  (`06`) does the opposite to CV² (Lumpy share roughly *doubles*, 3.2%→6.3%,
  at weekly grain) — a genuinely useful, non-obvious distinction between
  what time-aggregation and location-aggregation each do to this catalog's
  demand-pattern shape.
- **Bottom-Up beats Top-Down at both hierarchy levels, but not for the
  textbook reason.** Stage 3 found Bottom-Up wins decisively at national
  level (80.4% of products, portfolio RMSE 3.7% lower, bias magnitude 2.9x
  smaller) and ties at location level (59.8%/40.2%, pooled RMSE identical to
  4 decimals) — Top-Down never wins outright at either level, and the
  "Top-Down wins nationally, Bottom-Up wins locally" pattern the
  reconciliation literature would predict did not materialize. The traced
  cause: both approaches are built on the same SBA (α=0.1) engine, which
  Stage 2 showed badly lags this catalog's seasonal cycle (Jan-Apr/Oct-Dec
  high, May-Sep low). Bottom-Up sums 6 independently-lagged local fits (net
  annual bias -2.5%); Top-Down fits one lagged model on the aggregate (net
  annual bias +7.1%, 2.8x worse) — Bottom-Up's edge is a diversification
  effect from summing independently-timed local errors, not evidence it's
  capturing real location-specific demand signal Top-Down structurally can't
  see. This distinction matters for how much weight to put on the result if
  either method's underlying base model changes.
- **MinT is not feasible with today's data, decisively, at either level.**
  Stage 4 found both feasibility checks fail badly: holdout periods are
  12.1% (national) and 2.0% (location) of the rule-of-thumb minimum, and the
  resulting error-covariance matrices are *exactly* singular (not just
  ill-conditioned) — 63.9% of national-level and 94.0% of location-level
  eigen-directions are exactly zero, hitting the analytically-predicted rank
  ceiling (`n_obs - 1 = 364`) precisely at both levels.

## What remains open for the next phase

- **MinT's data-maturity gap is large and asymmetric across levels.**
  Reaching the 3x-5x rule-of-thumb floor needs ~7.3-12.8 more years of daily
  history at national grain (plausible on a multi-year horizon) but
  ~48.8-81.9 more years at location grain (not plausible ever, at this
  granularity). A full-sample-covariance MinT is realistically off the table
  for location-level reconciliation specifically, not just "not ready yet."
- **A shrinkage or diagonal (WLS) MinT variant remains untested and is the
  more promising path**, per Stage 4's discussion — these estimators are
  designed for exactly the n_series >> n_obs regime this catalog sits in,
  and don't require inverting a rank-deficient full covariance matrix. This
  is a different, smaller scope of work than what Stage 4 gated (the
  full-sample-covariance approach), and is a candidate for a future phase
  rather than a conclusion this workstream reached directly.
- **The Bottom-Up/Top-Down gap is entangled with SBA's seasonal-lag
  weakness**, not cleanly separable from it in this backtest. If a future
  phase swaps in a seasonally-aware base method (for either approach), this
  specific comparison's margins — and possibly its winner — could change.
  Re-running Stage 3 after any base-method change is advisable before
  treating "Bottom-Up wins" as a permanent conclusion rather than a
  conclusion conditional on today's SBA/ADIDA base models.

## Recommendation

**Carry Bottom-Up forward** as the reconciliation method for this catalog:
it wins or ties at both hierarchy levels in this backtest, requires no
covariance estimation (unlike MinT, which isn't viable with current data
maturity), and is simpler to maintain than Top-Down's location-share
disaggregation step. This is consistent with — and is the direct empirical
answer to — the open question Section 1 of the reconciliation context
document posed at the start of this workstream: yes, national aggregation
changes the demand-pattern picture (via CV², not ADI), but no, that alone
doesn't make Top-Down the better reconciliation choice once actually
backtested against Bottom-Up.
