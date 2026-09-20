# %% [markdown]
# # Demand pattern classification (Strategy 1)
#
# Classifies every (product_variant_id, location_id) series in the full
# 6,054-series catalog into Smooth / Intermittent / Erratic / Lumpy using the
# standard Syntetos-Boylan-Croston ADI/CV² thresholds. This is the routing
# step for Strategy 2 (Croston/SBA on non-smooth segments) and Strategy 3
# (multi-grain aggregation) — see `04_demand_classification_summary.md`.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from _shared.db_connection import get_scratch_schema, query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MARTS_SCRATCH = f"{get_scratch_schema()}.fact_demand_daily"
# Reuse 03's cached daily parquet if it's already been materialized, instead
# of re-querying Databricks for the same data. Copied into this stage's own
# output/ (not read from 03/output/ directly) to keep each stage's output/
# self-contained, matching the existing 01-03 convention.
BACKTEST_DAILY_CACHE = Path(__file__).resolve().parents[1] / "03_granularity_baselines" / "output" / "_fact_demand_daily.parquet"

KEYS = ["product_variant_id", "location_id"]
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49

# %% [markdown]
# ## 1. Load the daily series (same source table/columns as
# `03_granularity_baselines/run_baselines.py`'s `load_granularity("daily")`).

# %%
def load_daily() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_fact_demand_daily.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    if BACKTEST_DAILY_CACHE.exists():
        df = pd.read_parquet(BACKTEST_DAILY_CACHE)
    else:
        df = query_df(f"select date_day as period, {', '.join(KEYS)}, qty_sold_net from {MARTS_SCRATCH}")
        df["period"] = pd.to_datetime(df["period"]).dt.tz_localize(None)
        df["qty_sold_net"] = df["qty_sold_net"].astype("float32")
        for k in KEYS:
            df[k] = df[k].astype(str)

    df.to_parquet(cache_path)
    return df


# %% [markdown]
# ## 2. Per-series ADI/CV², left-trimmed to each series' own first sale.
#
# `fact_demand_daily`'s zero-fill spine starts from one global
# `min(placed_at)` across the whole catalog, not each product's own launch
# date (see `02_schema_design/02_ideal_schema_proposal.md`). Left-trimming to
# the first nonzero day avoids counting years of pre-launch zero-fill as
# "intermittency" for a later-launched product.

# %%
def compute_series_stats(qty: np.ndarray) -> dict:
    nonzero_idx = np.nonzero(qty)[0]
    if len(nonzero_idx) == 0:
        # never actually sold in this table — shouldn't occur given the
        # 6,054-pair scope is built from fct_sales/fct_daily_stock_levels
        # coverage, but guard against it rather than dividing by zero.
        return {"n_periods": 0, "n_nonzero_periods": 0, "adi": np.nan, "cv2": np.nan, "total_qty_sold_net": 0.0}

    trimmed = qty[nonzero_idx[0]:].astype(np.float64)
    n_periods = len(trimmed)
    nonzero_vals = trimmed[trimmed > 0]
    n_nonzero = len(nonzero_vals)
    adi = n_periods / n_nonzero

    if n_nonzero >= 2:
        cv2 = float(np.var(nonzero_vals, ddof=1) / np.mean(nonzero_vals) ** 2)
    else:
        # variance undefined on a single sale occurrence — flagged as its own
        # bucket downstream rather than forced to 0 or NaN-silenced.
        cv2 = np.nan

    return {
        "n_periods": n_periods,
        "n_nonzero_periods": n_nonzero,
        "adi": adi,
        "cv2": cv2,
        "total_qty_sold_net": float(trimmed.sum()),
    }


def classify_series(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(KEYS + ["period"])
    records = []
    for keys, g in df.groupby(KEYS, sort=False):
        stats = compute_series_stats(g["qty_sold_net"].to_numpy())
        records.append({"product_variant_id": keys[0], "location_id": keys[1], **stats})
    return pd.DataFrame(records)


# %% [markdown]
# ## 3. Classify into the four standard SBC quadrants (ADI=1.32, CV²=0.49).

# %%
def classify_category(row: pd.Series) -> str:
    if pd.isna(row["cv2"]):
        return "insufficient_data"
    smooth_adi = row["adi"] < ADI_THRESHOLD
    smooth_cv2 = row["cv2"] < CV2_THRESHOLD
    if smooth_adi and smooth_cv2:
        return "smooth"
    if not smooth_adi and smooth_cv2:
        return "intermittent"
    if smooth_adi and not smooth_cv2:
        return "erratic"
    return "lumpy"


# %%
if __name__ == "__main__":
    daily = load_daily()
    print(f"loaded {len(daily):,} daily rows, {daily.groupby(KEYS).ngroups:,} series")

    stats_df = classify_series(daily)
    stats_df["category"] = stats_df.apply(classify_category, axis=1)
    stats_df = stats_df[KEYS + ["adi", "cv2", "n_periods", "n_nonzero_periods", "total_qty_sold_net", "category"]]
    stats_df.to_csv(OUTPUT_DIR / "demand_classification.csv", index=False)

    total_volume = stats_df["total_qty_sold_net"].sum()
    summary = (
        stats_df.groupby("category")
        .agg(n_series=("category", "size"), total_qty=("total_qty_sold_net", "sum"))
        .reset_index()
    )
    summary["pct_series"] = round(100 * summary["n_series"] / len(stats_df), 1)
    summary["pct_volume"] = round(100 * summary["total_qty"] / total_volume, 1) if total_volume else 0.0
    summary = summary.sort_values("n_series", ascending=False)
    summary.to_csv(OUTPUT_DIR / "category_summary.csv", index=False)

    print(f"\ntotal series: {len(stats_df):,}")
    print(summary.to_string(index=False))
