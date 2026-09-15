# %% [markdown]
# # Hierarchical reconciliation — Stage 2: Top-Down
#
# Aggregates `fact_demand_daily` to national grain (per product, summed
# across all 6 locations), re-runs the Step A ADI/CV² diagnostic *at that
# grain* before picking a method (rather than assuming a Smooth segment
# emerges), fits the routed method, then disaggregates the national forecast
# back to product x location using each location's historical share of
# national demand. See `stage2_top_down_report.md` for the write-up; this
# script produces the numbers behind it.
#
# Reuses `03`'s `add_moving_average`/`add_ses` unmodified by giving the
# national series a constant `location_id = "NATIONAL"` column — those
# functions group by `03`'s own module-level `KEYS = ["product_variant_id",
# "location_id"]`, so a constant location_id makes every "group" exactly one
# product's national series, with no change to `03`'s code at all.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "03_granularity_baselines"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "04_demand_classification"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "05_croston_sba"))

import numpy as np
import pandas as pd

from run_baselines import most_recent_complete_year, compute_metrics, add_moving_average, add_ses, MA_WINDOWS, SES_ALPHA
from classify_demand_patterns import compute_series_stats, classify_category
from run_croston_sba import croston_sba, ALPHA as SBA_ALPHA

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
UPSTREAM_DAILY_CACHES = [
    Path(__file__).resolve().parents[2] / "05_croston_sba" / "output" / "_fact_demand_daily.parquet",
    Path(__file__).resolve().parents[2] / "04_demand_classification" / "output" / "_fact_demand_daily.parquet",
    Path(__file__).resolve().parents[2] / "03_granularity_baselines" / "output" / "_fact_demand_daily.parquet",
]
LOCATION_KEYS = ["product_variant_id", "location_id"]

# %% [markdown]
# ## 1. Load raw daily actuals (per product x location) and aggregate to
# national grain (per product, summed across locations). Tagged with a
# constant `location_id="NATIONAL"` so `03`'s KEYS-based functions apply
# unmodified.

# %%
def load_daily_location() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_fact_demand_daily.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    for upstream in UPSTREAM_DAILY_CACHES:
        if upstream.exists():
            df = pd.read_parquet(upstream)
            df.to_parquet(cache_path)
            return df
    raise FileNotFoundError("No cached daily parquet found upstream — run 03_granularity_baselines first.")


def build_national(daily_location: pd.DataFrame) -> pd.DataFrame:
    national = daily_location.groupby(["product_variant_id", "period"], as_index=False)["qty_sold_net"].sum()
    national["location_id"] = "NATIONAL"
    return national


# %% [markdown]
# ## 2. Re-run the Step A ADI/CV² diagnostic at national grain (`04`'s
# `compute_series_stats`/`classify_category`, reused verbatim, same
# thresholds), left-trimmed to each product's own first national sale.

# %%
def classify_national(national: pd.DataFrame) -> pd.DataFrame:
    national = national.sort_values(["product_variant_id", "period"])
    records = []
    for product_id, g in national.groupby("product_variant_id", sort=False):
        stats = compute_series_stats(g["qty_sold_net"].to_numpy())
        records.append({"product_variant_id": product_id, **stats})
    return pd.DataFrame(records)


# %% [markdown]
# ## 3. Fit the routed method per national series: Moving Average (`03`'s
# default daily window=28) for Smooth/Erratic, SBA (`05`'s alpha=0.1) for
# Intermittent/Lumpy/insufficient_data. Both are computed for every product
# regardless of routing (cheap, and gives a full comparison table like `05`
# did), but only the routed one is "the Top-Down forecast".

# %%
def fit_national_forecasts(national: pd.DataFrame) -> pd.DataFrame:
    df = add_moving_average(national.copy(), MA_WINDOWS["daily"])
    df = add_ses(df, SES_ALPHA)

    frames = []
    for product_id, g in df.sort_values("period").groupby("product_variant_id", sort=False):
        qty = g["qty_sold_net"].to_numpy()
        nonzero_idx = np.nonzero(qty)[0]
        g = g.copy()
        if len(nonzero_idx) == 0:
            g["sba_pred"] = np.nan
        else:
            sba_pred = np.full(len(g), np.nan)
            _, sba_trimmed = croston_sba(qty[nonzero_idx[0]:], alpha=SBA_ALPHA)
            sba_pred[nonzero_idx[0]:] = sba_trimmed
            g["sba_pred"] = sba_pred
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def route_forecast(row_category: str, ma_pred: float, sba_pred: float) -> float:
    if row_category in ("smooth", "erratic"):
        return ma_pred
    return sba_pred


# %% [markdown]
# ## 4. Location shares — each location's share of national demand per
# product, computed over the **pre-holdout training window**: all years
# strictly before the holdout year, from that product's own first national
# sale onward (same trim rationale as the classification). Static (one share
# per product x location), applied uniformly across every holdout-year day —
# the classic Top-Down assumption that relative shares are stable.

# %%
def compute_location_shares(daily_location: pd.DataFrame, holdout_year: int) -> pd.DataFrame:
    training = daily_location[daily_location["period"].dt.year < holdout_year]
    location_totals = training.groupby(LOCATION_KEYS)["qty_sold_net"].sum().reset_index(name="location_qty")
    product_totals = training.groupby("product_variant_id")["qty_sold_net"].sum().reset_index(name="product_qty")
    shares = location_totals.merge(product_totals, on="product_variant_id", how="left")
    shares["share"] = np.where(shares["product_qty"] > 0, shares["location_qty"] / shares["product_qty"], np.nan)
    return shares[LOCATION_KEYS + ["location_qty", "product_qty", "share"]]


# %%
if __name__ == "__main__":
    t0 = time.time()
    daily_location = load_daily_location()
    national = build_national(daily_location)
    print(f"loaded {len(daily_location):,} product x location daily rows -> {national.groupby('product_variant_id').ngroups:,} national product series")

    # --- Part 1: national-grain reclassification ---
    national_stats = classify_national(national)
    national_stats["category"] = national_stats.apply(classify_category, axis=1)
    national_stats.to_csv(OUTPUT_DIR / "national_classification.csv", index=False)

    total_volume = national_stats["total_qty_sold_net"].sum()
    national_category_summary = (
        national_stats.groupby("category").agg(n_series=("category", "size"), total_qty=("total_qty_sold_net", "sum")).reset_index()
    )
    national_category_summary["pct_series"] = round(100 * national_category_summary["n_series"] / len(national_stats), 1)
    national_category_summary["pct_volume"] = round(100 * national_category_summary["total_qty"] / total_volume, 1) if total_volume else 0.0
    national_category_summary = national_category_summary.sort_values("n_series", ascending=False)
    national_category_summary.to_csv(OUTPUT_DIR / "national_category_summary.csv", index=False)
    print("\nNational-grain classification:")
    print(national_category_summary.to_string(index=False))

    # --- Part 2: fit routed forecasts at national grain ---
    forecasted_path = OUTPUT_DIR / "_national_forecasts.parquet"
    if forecasted_path.exists():
        forecasted = pd.read_parquet(forecasted_path)
    else:
        forecasted = fit_national_forecasts(national)
        forecasted.to_parquet(forecasted_path)
    print(f"\nnational forecasts fit in {time.time() - t0:.1f}s")

    forecasted = forecasted.merge(national_stats[["product_variant_id", "category"]], on="product_variant_id", how="left")
    forecasted["top_down_pred"] = [
        route_forecast(cat, ma, sba) for cat, ma, sba in zip(forecasted["category"], forecasted["ma_pred"], forecasted["sba_pred"])
    ]

    holdout_year = most_recent_complete_year(forecasted["period"], "daily")
    print(f"holdout year: {holdout_year}")
    holdout_national = forecasted[forecasted["period"].dt.year == holdout_year].copy()

    # --- national-level metrics: per-product (routed forecast) + full method comparison ---
    rows = []
    for product_id, g in holdout_national.groupby("product_variant_id"):
        for method, col in [("top_down_routed", "top_down_pred"), ("moving_average", "ma_pred"), ("ses", "ses_pred"), ("sba", "sba_pred")]:
            m = compute_metrics(g["qty_sold_net"], g[col])
            rows.append({"product_variant_id": product_id, "method": method, "category": g["category"].iloc[0], **m})
    top_down_national_metrics = pd.DataFrame(rows)
    top_down_national_metrics.to_csv(OUTPUT_DIR / "top_down_national_metrics.csv", index=False)

    print("\n=== Top-Down national metrics, per method (median/mean across all 1,009 products) ===")
    for method in ["top_down_routed", "moving_average", "ses", "sba"]:
        sub = top_down_national_metrics[top_down_national_metrics["method"] == method]
        print(f"  {method:16s} rmse_mean={sub['rmse'].mean():.4f}  rmse_median={sub['rmse'].median():.4f}  bias_mean={sub['bias'].mean():+.4f}  smape_median={sub['smape'].median():.4f}")

    # --- seasonal bias breakdown: SBA's slow-adapting alpha=0.1 vs MA's
    # 28-day window, monthly portfolio totals, to explain why SBA's national
    # bias magnitude is much larger than MA's despite winning on RMSE. ---
    holdout_national["month"] = holdout_national["period"].dt.month
    seasonal = holdout_national.groupby("month", as_index=False).agg(
        actual=("qty_sold_net", "sum"), ma_pred=("ma_pred", "sum"), sba_pred=("sba_pred", "sum")
    )
    seasonal["bias_ma"] = seasonal["actual"] - seasonal["ma_pred"]
    seasonal["bias_sba"] = seasonal["actual"] - seasonal["sba_pred"]
    seasonal.to_csv(OUTPUT_DIR / "seasonal_bias_breakdown.csv", index=False)

    pct_products_underforecast = {
        method: round(100 * (top_down_national_metrics[(top_down_national_metrics["method"] == method)]["bias"] > 0).mean(), 1)
        for method in ["sba", "moving_average"]
    }
    median_abs_bias = {
        method: round(top_down_national_metrics[(top_down_national_metrics["method"] == method)]["bias"].abs().median(), 4)
        for method in ["sba", "moving_average"]
    }
    print("\n=== Seasonal bias breakdown (whole-portfolio monthly totals) ===")
    print(seasonal.to_string(index=False))
    print(f"\npct of products with positive (under-forecast) bias: sba={pct_products_underforecast['sba']}%  moving_average={pct_products_underforecast['moving_average']}%")
    print(f"median |bias| per product: sba={median_abs_bias['sba']}  moving_average={median_abs_bias['moving_average']}")

    # --- Part 3: location shares + disaggregation ---
    shares = compute_location_shares(daily_location, holdout_year)
    shares.to_csv(OUTPUT_DIR / "location_shares.csv", index=False)
    n_zero_share = int((shares["share"] == 0).sum())
    n_nan_share = int(shares["share"].isna().sum())
    print(f"\nlocation shares: {n_zero_share:,} zero-share pairs (no training-window sales), {n_nan_share:,} undefined (product had zero national training-window sales)")

    holdout_routed = holdout_national[["product_variant_id", "period", "top_down_pred"]]
    disaggregated = holdout_routed.merge(shares[LOCATION_KEYS + ["share"]], on="product_variant_id", how="left")
    disaggregated["location_pred"] = disaggregated["top_down_pred"] * disaggregated["share"]

    actual_holdout = daily_location[daily_location["period"].dt.year == holdout_year]
    location_compare = actual_holdout.merge(disaggregated[LOCATION_KEYS + ["period", "location_pred"]], on=LOCATION_KEYS + ["period"], how="left")

    location_rows = []
    for keys, g in location_compare.groupby(LOCATION_KEYS):
        m = compute_metrics(g["qty_sold_net"], g["location_pred"])
        location_rows.append({"product_variant_id": keys[0], "location_id": keys[1], **m})
    top_down_location_metrics = pd.DataFrame(location_rows)
    top_down_location_metrics.to_csv(OUTPUT_DIR / "top_down_location_metrics.csv", index=False)

    print("\n=== Top-Down disaggregated, location-level metrics (median/mean across 6,054 series) ===")
    print(f"  rmse_mean={top_down_location_metrics['rmse'].mean():.4f}  rmse_median={top_down_location_metrics['rmse'].median():.4f}  bias_mean={top_down_location_metrics['bias'].mean():+.4f}  smape_median={top_down_location_metrics['smape'].median():.4f}")
    print(f"  series fully excluded (0 forecastable rows): {(top_down_location_metrics['n_forecastable_rows']==0).sum():,} / {len(top_down_location_metrics):,}")
