# %%
"""Shared evaluation for Stage 3 model comparison — the team protocol in code.

Agreed convention (Slack, after review with Eros):

- **Target:** total demand over a 91-day window per (product_variant_id,
  location_id). Each model is free to fit at whatever grain suits it — weekly,
  daily — and sums its predictions into the window before calling this module.
  The modelling grain is therefore an implementation detail, not a source of
  divergence between team members.
- **Windows:** the same 4 rolling origins the Phase 1 close-out used
  (`09_baseline_close_out/walk_forward.py`), imported rather than re-derived:
  2024-12-31, 2025-04-01, 2025-07-01, 2025-09-30. Non-overlapping, 91 days.
- **Training:** data up to the cutoff only, refit per window.
- **Baseline to beat:** the `seasonal_naive_genuine_91d_v2` run in
  `/Shared/00_baseline`, which beats the moving average in all four windows.
- **Metrics:** RMSE and bias per series across the four windows, plus
  portfolio WAPE per window. Always reported per window, never only averaged.
  MAPE/sMAPE are excluded — `05_croston_sba` documented why they are
  structurally uninformative on this catalog.

Bias sign follows the Phase 1 close-out: `actual - forecast`, so a positive
bias means under-forecasting (the failure mode that causes stockouts).
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_FORECASTING = Path(__file__).resolve().parents[2]

# The repo already has two packages named `_shared` (forecasting/_shared and
# 10_feature_engineering/_shared) and this file adds a third, so importing by
# package name would resolve to whichever one Python's import cache saw first.
# Loading by file path avoids the clash — same technique
# `10_feature_engineering/_shared/panel_regression.py` uses, for the same reason.
sys.path.insert(0, str(_FORECASTING / "09_baseline_close_out"))
from walk_forward import make_periodic_cutoffs  # noqa: E402

KEYS = ["product_variant_id", "location_id"]
TRAIN_END = pd.Timestamp("2024-12-31")
VALIDATE_END = pd.Timestamp("2025-12-31")
HORIZON_DAYS = 91
STEP_DAYS = 91
BASELINE_RUN = "seasonal_naive_genuine_91d_v2"

def get_cutoffs() -> list:
    """The four agreed rolling origins, derived the same way the baseline was."""
    return make_periodic_cutoffs(TRAIN_END, VALIDATE_END, HORIZON_DAYS, STEP_DAYS, freq="D")

def evaluate(window_totals: pd.DataFrame, keys: list = None) -> dict:
    """Score one model against the protocol.

    `window_totals` must have one row per (series, cutoff) with columns
    `keys` + ["cutoff", "actual", "pred"], where actual/pred are already
    summed over the 91-day window.

    Returns a dict with:
      - `per_series`: RMSE and bias per series, across the four windows
      - `per_series_summary`: mean/median of those, one row
      - `portfolio`: one row per window — totals, bias and WAPE
    """

    keys = keys or KEYS
    required = {*keys, "cutoff", "actual", "pred"}
    missing = required - set(window_totals.columns)
    if missing:
        raise ValueError(f"window_totals is missing columns: {sorted(missing)}")
    
    df = window_totals.copy()
    df["error"] = df["actual"] - df["pred"]

    # RMSE per series over the four windows (n=4, so this is a real RMSE —
    # grouping by (series, cutoff) instead would leave n=1 and collapse it
    # into absolute error).
    per_series = (
        df.groupby(keys)
        .apply(
            lambda g: pd.Series(
                {"rmse": np.sqrt(np.mean(g["error"] ** 2)), "bias": g["error"].mean()}
            ),
            include_groups=False,
        )
        .reset_index()
    )

    per_series_summary = pd.DataFrame(
        [
            {
                "n_series": len(per_series),
                "rmse_mean": per_series["rmse"].mean(),
                "rmse_median": per_series["rmse"].median(),
                "bias_mean": per_series["bias"].mean(),
            }
        ]
    )

    # Portfolio, per window. WAPE keeps the Phase 1 close-out's definition:
    # per-series absolute errors summed, over total actual demand.
    portfolio = (
        df.groupby("cutoff")
        .agg(
            actual_total=("actual", "sum"),
            forecast_total=("pred", "sum"),
            abs_error=("error", lambda s: s.abs().sum()),
        )
        .reset_index()
    )
    portfolio["bias"] = portfolio["actual_total"] - portfolio["forecast_total"]
    portfolio["wape_pct"] = 100 * portfolio["abs_error"] / portfolio["actual_total"]

    return {
        "per_series": per_series,
        "per_series_summary": per_series_summary,
        "portfolio": portfolio[["cutoff", "actual_total", "forecast_total", "bias", "wape_pct"]],
    }

# %% [markdown]
# ## Category level
#
# The protocol reports at two levels: SKU x location (comparable with the
# committed baseline, and what the client asked for) and category x location
# (where the error is small enough to act on). Aggregating the *window totals*
# -- not re-forecasting at category grain -- keeps both levels honest: they
# describe the same predictions, summed differently.

# %%
_DB_CONNECTION_PATH = _FORECASTING / "_shared" / "db_connection.py"
_spec = importlib.util.spec_from_file_location("forecasting_shared_db_connection", _DB_CONNECTION_PATH)
_db_connection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_connection)
query_df = _db_connection.query_df
PROD_MARTS = _db_connection.PROD_MARTS

_CATEGORY_MAP = None


def _load_category_map() -> pd.DataFrame:
    """variant -> category, from the shared prod marts. Cached per process."""
    global _CATEGORY_MAP
    if _CATEGORY_MAP is None:
        _CATEGORY_MAP = query_df(
            f"""
            SELECT DISTINCT product_variant_id,
                   COALESCE(category_name, 'Uncategorised') AS category_name
            FROM {PROD_MARTS}.dim_products
            """
        )
        _CATEGORY_MAP["product_variant_id"] = _CATEGORY_MAP["product_variant_id"].astype(str)
    return _CATEGORY_MAP


def to_category_level(window_totals: pd.DataFrame) -> pd.DataFrame:
    """Sum SKU-level window totals up to category x location, ready for evaluate()."""
    df = window_totals.copy()
    df["product_variant_id"] = df["product_variant_id"].astype(str)
    mapped = df.merge(_load_category_map(), on="product_variant_id", how="left")

    unmapped = int(mapped["category_name"].isna().sum())
    if unmapped:
        raise ValueError(f"{unmapped} rows have no category in dim_products -- check the variant ids")

    return mapped.groupby(["category_name", "location_id", "cutoff"], as_index=False)[["actual", "pred"]].sum()


# %% [markdown]
# ## Comparison against the committed baseline
#
# Read from the tracked CSV rather than MLflow, so this works offline and every
# model is compared against exactly the numbers in the repo.

# %%
BASELINE_PORTFOLIO_CSV = _FORECASTING / "09_baseline_close_out" / "output" / "genuine_baseline_metrics_portfolio.csv"
BASELINE_METHOD = "seasonal_naive"


def load_baseline_portfolio() -> pd.DataFrame:
    """The champion's per-window portfolio numbers (SKU x location level)."""
    df = pd.read_csv(BASELINE_PORTFOLIO_CSV)
    df = df[df["baseline"] == BASELINE_METHOD].copy()
    df["cutoff"] = pd.to_datetime(df["cutoff"])
    return df[["cutoff", "actual_total", "forecast_total", "bias", "wape_pct"]]


def compare_to_baseline(portfolio: pd.DataFrame, tolerance_pct: float = 0.5) -> pd.DataFrame:
    """Join a model's portfolio to the champion's, per window. SKU level only.

    Also checks that both sides saw the same demand: if `actual_total` differs
    from the baseline's by more than `tolerance_pct`, the window definition or
    the source filter diverged, and the WAPE comparison is not meaningful.
    """
    base = load_baseline_portfolio().add_suffix("_baseline").rename(columns={"cutoff_baseline": "cutoff"})
    merged = portfolio.merge(base, on="cutoff", how="inner")

    if len(merged) != len(portfolio):
        raise ValueError(f"cutoffs do not line up: {len(portfolio)} model windows, {len(merged)} matched")

    drift = 100 * (merged["actual_total"] - merged["actual_total_baseline"]).abs() / merged["actual_total_baseline"]
    if (drift > tolerance_pct).any():
        worst = drift.max()
        print(
            f"WARNING: actual demand differs from the baseline by up to {worst:.2f}% "
            f"(tolerance {tolerance_pct}%) -- same windows, different source or filter?"
        )

    merged["wape_delta_pp"] = merged["wape_pct"] - merged["wape_pct_baseline"]
    merged["beats_baseline"] = merged["wape_delta_pp"] < 0
    return merged[["cutoff", "actual_total", "wape_pct", "wape_pct_baseline", "wape_delta_pp", "beats_baseline"]]


# %%
if __name__ == "__main__":
    # Mechanics smoke test: synthetic data, no database, no model.
    cutoffs = get_cutoffs()
    print(f"Cutoffs ({len(cutoffs)}): {[c.date() for c in cutoffs]}")

    demo = pd.DataFrame(
        [
            {"product_variant_id": p, "location_id": "L1", "cutoff": c, "actual": 100, "pred": 80}
            for p in ("A", "B", "C")
            for c in cutoffs
        ]
    )
    out = evaluate(demo)
    print("\nper_series_summary:")
    print(out["per_series_summary"].to_string(index=False))
    print("\nportfolio:")
    print(out["portfolio"].to_string(index=False))

    perfect = demo.assign(pred=demo["actual"])
    assert evaluate(perfect)["portfolio"]["wape_pct"].eq(0).all(), "a perfect forecast must give WAPE 0"
    print("\nSmoke test passed.")

    print("\nBaseline to beat (seasonal_naive_genuine_91d_v2):")
    print(load_baseline_portfolio().to_string(index=False))
    print("\nto_category_level() needs the warehouse -- not exercised in this offline smoke test.")