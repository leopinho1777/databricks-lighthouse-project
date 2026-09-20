# %% [markdown]
# # Croston / SBA backtest (Strategy 2 — Step B)
#
# Full-catalog Croston's method and its Syntetos-Boylan Approximation (SBA)
# bias correction, backtested at daily grain against `fact_demand_daily`.
# `04_demand_classification` found the entire 6,054-series catalog lands
# Intermittent (96.8%) or Lumpy (3.2%) at daily grain under the standard
# ADI=1.32/CV²=0.49 thresholds — no Smooth segment to exclude — so this run
# covers the full catalog, matching that stage's recommendation. See
# `05_croston_sba_summary.md` for the write-up; this script produces the
# numbers behind it.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_granularity_baselines"))

import numpy as np
import pandas as pd

from _shared.db_connection import get_scratch_schema, query_df
from run_baselines import most_recent_complete_year, compute_metrics

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MARTS_SCRATCH = f"{get_scratch_schema()}.fact_demand_daily"
# Reuse 03's cached daily parquet (or 04's, if 03's was cleaned up) instead of
# re-querying Databricks for data already pulled twice. Copied into this
# stage's own output/ to keep each stage's output/ self-contained, matching
# the 01-04 convention.
UPSTREAM_DAILY_CACHES = [
    Path(__file__).resolve().parents[1] / "03_granularity_baselines" / "output" / "_fact_demand_daily.parquet",
    Path(__file__).resolve().parents[1] / "04_demand_classification" / "output" / "_fact_demand_daily.parquet",
]
CLASSIFICATION_CSV = Path(__file__).resolve().parents[1] / "04_demand_classification" / "output" / "demand_classification.csv"
DAILY_BASELINE_METRICS_CSV = Path(__file__).resolve().parents[1] / "03_granularity_baselines" / "output" / "metrics_by_granularity_baseline.csv"

KEYS = ["product_variant_id", "location_id"]
ALPHA = 0.1  # standard Croston/SBA smoothing constant (Syntetos & Boylan, 2005)

# %% [markdown]
# ## 1. Load the daily series (same source/columns as `03`/`04`).

# %%
def load_daily() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_fact_demand_daily.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    for upstream in UPSTREAM_DAILY_CACHES:
        if upstream.exists():
            df = pd.read_parquet(upstream)
            df.to_parquet(cache_path)
            return df

    df = query_df(f"select date_day as period, {', '.join(KEYS)}, qty_sold_net from {MARTS_SCRATCH}")
    df["period"] = pd.to_datetime(df["period"]).dt.tz_localize(None)
    df["qty_sold_net"] = df["qty_sold_net"].astype("float32")
    for k in KEYS:
        df[k] = df[k].astype(str)
    df.to_parquet(cache_path)
    return df


# %% [markdown]
# ## 2. Croston's method + SBA, left-trimmed to each series' own first sale
# (same trimming rationale as `04`'s ADI/CV² — the zero-fill spine starts
# from one global `min(placed_at)`, not each product's own launch date).
#
# Sequential, one-step-ahead: `forecast[t]` is set from state accumulated
# through `t-1` *before* period `t`'s actual is used to update state — no
# lookahead. State only updates on non-zero-demand periods (Croston's whole
# point is to smooth demand *size* and *inter-demand interval* separately,
# rather than smoothing a mostly-zero series directly like SES would).

# %%
def croston_sba(qty: np.ndarray, alpha: float = ALPHA) -> tuple[np.ndarray, np.ndarray]:
    """Return (croston_pred, sba_pred), same length as `qty`, `qty[0]` assumed > 0.

    croston_pred[t] = z/p as of just before period t (NaN until the first
    demand has been observed, i.e. index 0 always NaN here since state only
    exists *after* processing the first occurrence).
    sba_pred[t] = (1 - alpha/2) * croston_pred[t] — the multiplicative bias
    correction Syntetos & Boylan (2005) proved Croston's method needs.
    """
    n = len(qty)
    croston_pred = np.full(n, np.nan)
    z = 0.0
    p = 1.0
    have_state = False
    q = 0  # periods since the last non-zero-demand occurrence
    for t in range(n):
        if have_state:
            croston_pred[t] = z / p
        q += 1
        if qty[t] > 0:
            if not have_state:
                z = qty[t]
                p = float(q)
                have_state = True
            else:
                z = alpha * qty[t] + (1 - alpha) * z
                p = alpha * q + (1 - alpha) * p
            q = 0
    sba_pred = (1 - alpha / 2) * croston_pred
    return croston_pred, sba_pred


def run_croston_for_series(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(KEYS + ["period"])
    frames = []
    for keys, g in df.groupby(KEYS, sort=False):
        qty = g["qty_sold_net"].to_numpy()
        nonzero_idx = np.nonzero(qty)[0]
        if len(nonzero_idx) == 0:
            continue
        trimmed = g.iloc[nonzero_idx[0]:].copy()
        croston_pred, sba_pred = croston_sba(trimmed["qty_sold_net"].to_numpy())
        trimmed["croston_pred"] = croston_pred
        trimmed["sba_pred"] = sba_pred
        frames.append(trimmed)
    return pd.concat(frames, ignore_index=True)


# %% [markdown]
# ## 3. Metrics on the holdout year only (same `most_recent_complete_year` /
# `compute_metrics` as `03`, reused verbatim so every stage's numbers are
# directly comparable).

# %%
def summarize_by_series(holdout: pd.DataFrame, col: str, label: str) -> pd.DataFrame:
    rows = []
    for keys, g in holdout.groupby(KEYS):
        m = compute_metrics(g["qty_sold_net"], g[col])
        rows.append({"product_variant_id": keys[0], "location_id": keys[1], "method": label, **m})
    return pd.DataFrame(rows)


def portfolio_metrics(holdout: pd.DataFrame, col: str, label: str) -> dict:
    portfolio = holdout.groupby("period", as_index=False).agg(
        qty_sold_net=("qty_sold_net", "sum"), pred=(col, "sum")
    )
    m = compute_metrics(portfolio["qty_sold_net"], portfolio["pred"])
    return {"method": label, **m}


# %%
if __name__ == "__main__":
    t0 = time.time()
    daily = load_daily()
    print(f"loaded {len(daily):,} daily rows, {daily.groupby(KEYS).ngroups:,} series")

    forecasts_path = OUTPUT_DIR / "_croston_sba_forecasts.parquet"
    if forecasts_path.exists():
        forecasted = pd.read_parquet(forecasts_path)
    else:
        forecasted = run_croston_for_series(daily)
        forecasted.to_parquet(forecasts_path)
    print(f"Croston/SBA state machine run in {time.time() - t0:.1f}s")

    holdout_year = most_recent_complete_year(forecasted["period"], "daily")
    print(f"holdout year: {holdout_year}")
    holdout = forecasted[forecasted["period"].dt.year == holdout_year].copy()

    # --- per-series metrics, one row per (series, method) ---
    per_series_frames = [
        summarize_by_series(holdout, "croston_pred", "croston"),
        summarize_by_series(holdout, "sba_pred", "sba"),
    ]
    per_series_df = pd.concat(per_series_frames, ignore_index=True)
    per_series_df.to_csv(OUTPUT_DIR / "croston_sba_per_series_metrics.csv", index=False)

    # --- per-series x demand-pattern-category rollup (04's routing labels) ---
    classification = pd.read_csv(CLASSIFICATION_CSV, dtype={"product_variant_id": str, "location_id": str})
    per_series_with_cat = per_series_df.merge(
        classification[KEYS + ["category"]], on=KEYS, how="left"
    )
    category_summary = (
        per_series_with_cat.groupby(["method", "category"])
        .agg(
            n_series=("rmse", "size"),
            rmse_mean=("rmse", "mean"),
            rmse_median=("rmse", "median"),
            bias_mean=("bias", "mean"),
            mape_median=("mape", "median"),
            smape_mean=("smape", "mean"),
            smape_median=("smape", "median"),
            pct_series_fully_excluded=("n_forecastable_rows", lambda s: round(100 * (s == 0).mean(), 1)),
        )
        .reset_index()
    )
    category_summary.to_csv(OUTPUT_DIR / "croston_sba_by_category.csv", index=False)

    # --- portfolio-level pooled summary, matching 03's summary_df shape ---
    overall_rows = []
    for method, col in [("croston", "croston_pred"), ("sba", "sba_pred")]:
        sub = per_series_df[per_series_df["method"] == method]
        overall_rows.append(
            {
                "method": method,
                "n_series": len(sub),
                "n_series_fully_excluded": int((sub["n_forecastable_rows"] == 0).sum()),
                "pct_series_fully_excluded": round(100 * (sub["n_forecastable_rows"] == 0).mean(), 1),
                "rmse_mean": sub["rmse"].mean(),
                "rmse_median": sub["rmse"].median(),
                "bias_mean": sub["bias"].mean(),
                "mape_mean": sub["mape"].mean(),
                "mape_median": sub["mape"].median(),
                "smape_mean": sub["smape"].mean(),
                "smape_median": sub["smape"].median(),
            }
        )
    overall_df = pd.DataFrame(overall_rows)

    # --- pull in 03's daily-grain baseline numbers for a direct side-by-side ---
    daily_baselines = pd.read_csv(DAILY_BASELINE_METRICS_CSV)
    daily_baselines = daily_baselines[daily_baselines["granularity"] == "daily"].rename(columns={"baseline": "method"})
    comparison_cols = ["method", "n_series", "pct_series_fully_excluded", "rmse_mean", "rmse_median", "bias_mean", "mape_median", "smape_mean", "smape_median"]
    comparison_df = pd.concat([daily_baselines[comparison_cols], overall_df[comparison_cols]], ignore_index=True)
    comparison_df.to_csv(OUTPUT_DIR / "croston_sba_vs_baselines.csv", index=False)

    # --- portfolio (whole-catalog summed) total, sanity upper bound like 03 ---
    portfolio_rows = [portfolio_metrics(holdout, "croston_pred", "croston"), portfolio_metrics(holdout, "sba_pred", "sba")]
    portfolio_df = pd.DataFrame(portfolio_rows)
    portfolio_df.to_csv(OUTPUT_DIR / "croston_sba_portfolio_metrics.csv", index=False)

    print("\n=== Croston/SBA vs. 03's daily baselines (per-series, median across full catalog) ===")
    print(comparison_df.to_string(index=False))

    print("\n=== Croston/SBA by demand-pattern category ===")
    print(category_summary.to_string(index=False))

    print("\n=== Whole-portfolio total (sanity upper bound) ===")
    print(portfolio_df[["method", "smape", "mape", "rmse", "bias"]].to_string(index=False))
