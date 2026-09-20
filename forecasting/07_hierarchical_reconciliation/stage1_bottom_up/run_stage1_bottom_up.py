# %% [markdown]
# # Hierarchical reconciliation — Stage 1: Bottom-Up
#
# Sums `06_multi_grain`'s per-series recommended forecast (the better of
# `05`'s native daily SBA or `06`'s ADIDA, chosen per series) across all 6
# locations to produce a **national** demand forecast per product, with no
# separate national-level model at all — the defining trait of Bottom-Up.
# See `stage1_bottom_up_report.md` for the write-up; this script produces the
# numbers behind it.
#
# Per the reconciliation context document's Section 3.5 prerequisite, this
# stage consumes `06`'s committed per-series/per-day forecast cache directly
# (same reuse-in-place convention `04` used for `03`'s cache and `06` used
# for `05`'s) rather than re-deriving it.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "03_granularity_baselines"))

import numpy as np
import pandas as pd

from run_baselines import most_recent_complete_year, compute_metrics

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
RECOMMENDED_FORECASTS = Path(__file__).resolve().parents[2] / "06_multi_grain" / "output" / "_recommended_forecasts.parquet"

KEYS = ["product_variant_id", "location_id"]

# %% [markdown]
# ## 1. Load `06`'s per-series recommended forecast (already the better of
# native daily SBA / ADIDA, chosen per series on holdout RMSE).

# %%
def load_recommended() -> pd.DataFrame:
    df = pd.read_parquet(RECOMMENDED_FORECASTS)
    return df


# %% [markdown]
# ## 2. Sum forecasts and actuals across all locations, per product, per
# period — the Bottom-Up national series. Rows where a location's forecast
# is still `NaN` (pre-trim start-up) are excluded from the sum for that
# product/period rather than silently treated as a 0 contribution.

# %%
def aggregate_national(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["product_variant_id", "period"], as_index=False).agg(
        qty_sold_net=("qty_sold_net", "sum"),
        national_pred=("recommended_pred", lambda s: np.nan if s.isna().all() else s.sum(skipna=True)),
        n_locations_reporting=("recommended_pred", lambda s: int(s.notna().sum())),
        n_locations_total=("recommended_pred", "size"),
    )
    return grouped


# %% [markdown]
# ## 3. Metrics — computed on the summed national series directly (per
# product, and for the whole-catalog portfolio total), never by averaging
# per-location metrics, since error aggregation and value aggregation behave
# differently. Same `most_recent_complete_year`/`compute_metrics` as every
# prior stage, so these numbers are directly comparable.

# %%
def per_product_metrics(holdout: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for product_id, g in holdout.groupby("product_variant_id"):
        m = compute_metrics(g["qty_sold_net"], g["national_pred"])
        rows.append({"product_variant_id": product_id, **m})
    return pd.DataFrame(rows)


# %%
if __name__ == "__main__":
    t0 = time.time()
    recommended = load_recommended()
    print(f"loaded {len(recommended):,} rows, {recommended.groupby(KEYS).ngroups:,} product x location series")

    national = aggregate_national(recommended)
    print(f"aggregated to {national.groupby('product_variant_id').ngroups:,} national product series in {time.time()-t0:.1f}s")
    # sanity: every product should be backed by all 6 locations in most rows
    incomplete = national[national["n_locations_reporting"] < national["n_locations_total"]]
    print(f"product/period rows with at least one location still NaN (pre-trim start-up): {len(incomplete):,} / {len(national):,}")

    holdout_year = most_recent_complete_year(national["period"], "daily")
    print(f"holdout year: {holdout_year}")
    holdout = national[national["period"].dt.year == holdout_year].copy()

    # --- per-product national metrics ---
    product_metrics = per_product_metrics(holdout)
    product_metrics.to_csv(OUTPUT_DIR / "bottom_up_national_metrics.csv", index=False)

    summary = {
        "n_products": len(product_metrics),
        "rmse_mean": product_metrics["rmse"].mean(),
        "rmse_median": product_metrics["rmse"].median(),
        "bias_mean": product_metrics["bias"].mean(),
        "mape_mean": product_metrics["mape"].mean(),
        "mape_median": product_metrics["mape"].median(),
        "smape_mean": product_metrics["smape"].mean(),
        "smape_median": product_metrics["smape"].median(),
    }
    print("\n=== Bottom-Up national, per-product metrics (median/mean across all products) ===")
    for k, v in summary.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    # --- whole-catalog portfolio total (all products+locations summed per day) ---
    portfolio = holdout.groupby("period", as_index=False).agg(qty_sold_net=("qty_sold_net", "sum"), national_pred=("national_pred", "sum"))
    portfolio_metrics = compute_metrics(portfolio["qty_sold_net"], portfolio["national_pred"])
    portfolio_df = pd.DataFrame([{"level": "whole_catalog_portfolio", **portfolio_metrics}])
    portfolio_df.to_csv(OUTPUT_DIR / "bottom_up_portfolio_metrics.csv", index=False)

    print("\n=== Whole-catalog portfolio total (all products+locations summed) ===")
    print(portfolio_df.to_string(index=False))
