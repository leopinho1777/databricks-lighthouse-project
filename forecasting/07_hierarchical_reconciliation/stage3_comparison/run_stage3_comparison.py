# %% [markdown]
# # Hierarchical reconciliation — Stage 3: Bottom-Up vs. Top-Down comparison
#
# Direct, apples-to-apples comparison of Stage 1 (Bottom-Up) and Stage 2
# (Top-Down) at both levels each naturally produces a forecast for:
#
# 1. **National** — Stage 1 sums `05`/`06`'s per-location forecasts up;
#    Stage 2 fits SBA directly on the national aggregate. Both levels'
#    numbers are already computed; this stage lines them up side by side.
# 2. **Location** — Stage 1's native per-series output (`05`/`06`'s
#    recommended per-series forecast) vs. Stage 2's national forecast
#    disaggregated down via historical location shares.
#
# See `stage3_comparison_report.md` for the write-up; this script produces
# the numbers behind it.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2_top_down"))

import numpy as np
import pandas as pd

from run_stage2_top_down import route_forecast

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

STAGE1_DIR = Path(__file__).resolve().parents[1] / "stage1_bottom_up" / "output"
STAGE2_DIR = Path(__file__).resolve().parents[1] / "stage2_top_down" / "output"
STAGE6_DIR = Path(__file__).resolve().parents[2] / "06_multi_grain" / "output"
RECOMMENDED_FORECASTS = Path(__file__).resolve().parents[2] / "06_multi_grain" / "output" / "_recommended_forecasts.parquet"
CLASSIFICATION_CSV = Path(__file__).resolve().parents[2] / "04_demand_classification" / "output" / "demand_classification.csv"

KEYS = ["product_variant_id", "location_id"]

# %% [markdown]
# ## 1. National-level comparison — per-product, plus whole-catalog portfolio
# total (Top-Down's portfolio total isn't in Stage 2's own output, so it's
# derived here from Stage 2's cached national-forecast parquet, reusing
# Stage 2's own `route_forecast` rather than re-deriving the routing rule).

# %%
def load_national_comparison() -> pd.DataFrame:
    bu = pd.read_csv(STAGE1_DIR / "bottom_up_national_metrics.csv")
    td = pd.read_csv(STAGE2_DIR / "top_down_national_metrics.csv")
    td = td[td["method"] == "top_down_routed"].drop(columns=["method"])
    merged = bu.merge(td, on="product_variant_id", suffixes=("_bottom_up", "_top_down"))
    return merged


def top_down_portfolio_total() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2_top_down"))
    from run_stage2_top_down import most_recent_complete_year, compute_metrics  # noqa: reused verbatim from 03

    forecasted = pd.read_parquet(STAGE2_DIR / "_national_forecasts.parquet")
    # `_national_forecasts.parquet`'s product_variant_id is str (inherited from
    # 05's original parquet cache); national_classification.csv was written
    # from that same str-keyed data but loses the dtype on round-trip through
    # CSV — cast back to str here so the merge below actually matches.
    classification = pd.read_csv(STAGE2_DIR / "national_classification.csv", dtype={"product_variant_id": str})[["product_variant_id", "category"]]
    forecasted = forecasted.merge(classification, on="product_variant_id", how="left")
    forecasted["top_down_pred"] = [
        route_forecast(cat, ma, sba) for cat, ma, sba in zip(forecasted["category"], forecasted["ma_pred"], forecasted["sba_pred"])
    ]
    holdout_year = most_recent_complete_year(forecasted["period"], "daily")
    holdout = forecasted[forecasted["period"].dt.year == holdout_year]
    portfolio = holdout.groupby("period", as_index=False).agg(qty_sold_net=("qty_sold_net", "sum"), top_down_pred=("top_down_pred", "sum"))
    return compute_metrics(portfolio["qty_sold_net"], portfolio["top_down_pred"])


# %% [markdown]
# ## 2. Location-level comparison — Bottom-Up's native per-series forecast
# (`06`'s recommended choice per series, reconstructed from `06`'s own
# tracked per-method metrics + its `method_chosen` column — no rerun needed)
# vs. Stage 2's disaggregated Top-Down.

# %%
def load_bottom_up_native_location_metrics() -> pd.DataFrame:
    per_method = pd.read_csv(STAGE6_DIR / "adida_daily_metrics.csv")
    recommendation = pd.read_csv(STAGE6_DIR / "method_recommendation.csv")[KEYS + ["method_chosen"]]
    method_map = {"daily_sba": "daily_sba_native", "adida": "adida_disaggregated"}
    recommendation["method"] = recommendation["method_chosen"].map(method_map)
    native = recommendation.merge(per_method, on=KEYS + ["method"], how="left")
    return native.drop(columns=["method_chosen", "method"])


def load_location_comparison() -> pd.DataFrame:
    bu_native = load_bottom_up_native_location_metrics()
    td_disagg = pd.read_csv(STAGE2_DIR / "top_down_location_metrics.csv")
    merged = bu_native.merge(td_disagg, on=KEYS, suffixes=("_bottom_up", "_top_down"))
    return merged


# %% [markdown]
# ## 3. Seasonal bias breakdown — Bottom-Up's own monthly national bias,
# alongside `06`'s cached Top-Down monthly bias (`stage2_top_down`'s own
# `output/seasonal_bias_breakdown.csv`), to check whether Bottom-Up's better
# national bias number (Section 1) comes from actually tracking the season,
# or from a similar month-to-month lag that happens to net out better.

# %%
def bottom_up_seasonal_bias(holdout_year: int) -> pd.DataFrame:
    recommended = pd.read_parquet(RECOMMENDED_FORECASTS)
    recommended = recommended[recommended["period"].dt.year == holdout_year]
    national = recommended.groupby("period", as_index=False).agg(actual=("qty_sold_net", "sum"), bu_pred=("recommended_pred", "sum"))
    national["month"] = national["period"].dt.month
    monthly = national.groupby("month", as_index=False).agg(actual=("actual", "sum"), bu_pred=("bu_pred", "sum"))
    monthly["bias_bu"] = monthly["actual"] - monthly["bu_pred"]
    return monthly


# %%
if __name__ == "__main__":
    # --- National ---
    national = load_national_comparison()
    national.to_csv(OUTPUT_DIR / "national_comparison_detail.csv", index=False)

    national_win = (national["rmse_bottom_up"] < national["rmse_top_down"]).mean()
    print(f"National level — Bottom-Up wins RMSE on {100*national_win:.1f}% of {len(national):,} products")
    print(f"  Bottom-Up : rmse_mean={national['rmse_bottom_up'].mean():.4f}  rmse_median={national['rmse_bottom_up'].median():.4f}  bias_mean={national['bias_bottom_up'].mean():+.4f}")
    print(f"  Top-Down  : rmse_mean={national['rmse_top_down'].mean():.4f}  rmse_median={national['rmse_top_down'].median():.4f}  bias_mean={national['bias_top_down'].mean():+.4f}")

    bu_portfolio = pd.read_csv(STAGE1_DIR / "bottom_up_portfolio_metrics.csv").iloc[0].to_dict()
    td_portfolio = top_down_portfolio_total()
    print(f"\nNational portfolio total — Bottom-Up: rmse={bu_portfolio['rmse']:.2f} bias={bu_portfolio['bias']:+.2f}")
    print(f"National portfolio total — Top-Down : rmse={td_portfolio['rmse']:.2f} bias={td_portfolio['bias']:+.2f}")

    # --- seasonal bias: is Bottom-Up's better national bias number because
    # it tracks the season, or because its month-to-month lag happens to net
    # out better than Top-Down's? ---
    holdout_year_bu = 2025  # matches most_recent_complete_year across every prior stage
    bu_seasonal = bottom_up_seasonal_bias(holdout_year_bu)
    td_seasonal = pd.read_csv(STAGE2_DIR / "seasonal_bias_breakdown.csv")
    seasonal_comparison = bu_seasonal.merge(td_seasonal[["month", "sba_pred", "bias_sba"]], on="month").rename(
        columns={"sba_pred": "td_pred", "bias_sba": "bias_td"}
    )
    seasonal_comparison.to_csv(OUTPUT_DIR / "seasonal_bias_comparison.csv", index=False)
    print("\n=== Seasonal bias comparison (whole-portfolio monthly totals) ===")
    print(seasonal_comparison.to_string(index=False))
    print(f"\nnet annual bias pct: bottom_up={100*bu_seasonal['bias_bu'].sum()/bu_seasonal['actual'].sum():.1f}%  top_down={100*td_seasonal['bias_sba'].sum()/td_seasonal['actual'].sum():.1f}%")

    # --- Location ---
    location = load_location_comparison()
    location.to_csv(OUTPUT_DIR / "location_comparison_detail.csv", index=False)

    # note: unlike 05/06's own scripts, every dataframe here is re-read from
    # this workstream's own tracked CSVs (not the original str-typed parquet
    # caches), so KEYS are left to pandas' natural int64 inference throughout
    # — forcing str here alone (like 05/06 do against the parquet-derived
    # frames) would silently produce an all-NaN merge against the int64 KEYS
    # in `location`.
    classification = pd.read_csv(CLASSIFICATION_CSV)
    location_with_cat = location.merge(classification[KEYS + ["category"]], on=KEYS, how="left")

    location_win = (location["rmse_bottom_up"] < location["rmse_top_down"]).mean()
    print(f"\nLocation level — Bottom-Up wins RMSE on {100*location_win:.1f}% of {len(location):,} series")
    print(f"  Bottom-Up : rmse_mean={location['rmse_bottom_up'].mean():.4f}  rmse_median={location['rmse_bottom_up'].median():.4f}  bias_mean={location['bias_bottom_up'].mean():+.4f}")
    print(f"  Top-Down  : rmse_mean={location['rmse_top_down'].mean():.4f}  rmse_median={location['rmse_top_down'].median():.4f}  bias_mean={location['bias_top_down'].mean():+.4f}")

    category_rollup = (
        location_with_cat.groupby("category")
        .agg(
            n_series=("rmse_bottom_up", "size"),
            bottom_up_rmse_mean=("rmse_bottom_up", "mean"),
            top_down_rmse_mean=("rmse_top_down", "mean"),
            bottom_up_bias_mean=("bias_bottom_up", "mean"),
            top_down_bias_mean=("bias_top_down", "mean"),
        )
        .reset_index()
    )
    category_rollup["pct_bottom_up_wins_rmse"] = (
        location_with_cat.groupby("category")[["rmse_bottom_up", "rmse_top_down"]]
        .apply(lambda g: round(100 * (g["rmse_bottom_up"] < g["rmse_top_down"]).mean(), 1))
        .values
    )
    category_rollup.to_csv(OUTPUT_DIR / "location_comparison_by_category.csv", index=False)
    print("\n=== Location-level comparison by demand-pattern category ===")
    print(category_rollup.to_string(index=False))

    # --- headline method_comparison.csv, the plan's named deliverable ---
    method_comparison = pd.DataFrame(
        [
            {"level": "national", "method": "bottom_up", "n_series": len(national), "rmse_mean": national["rmse_bottom_up"].mean(), "rmse_median": national["rmse_bottom_up"].median(), "bias_mean": national["bias_bottom_up"].mean(), "pct_rmse_wins": round(100 * national_win, 1)},
            {"level": "national", "method": "top_down", "n_series": len(national), "rmse_mean": national["rmse_top_down"].mean(), "rmse_median": national["rmse_top_down"].median(), "bias_mean": national["bias_top_down"].mean(), "pct_rmse_wins": round(100 * (1 - national_win), 1)},
            {"level": "national_portfolio", "method": "bottom_up", "n_series": 1, "rmse_mean": bu_portfolio["rmse"], "rmse_median": bu_portfolio["rmse"], "bias_mean": bu_portfolio["bias"], "pct_rmse_wins": np.nan},
            {"level": "national_portfolio", "method": "top_down", "n_series": 1, "rmse_mean": td_portfolio["rmse"], "rmse_median": td_portfolio["rmse"], "bias_mean": td_portfolio["bias"], "pct_rmse_wins": np.nan},
            {"level": "location", "method": "bottom_up", "n_series": len(location), "rmse_mean": location["rmse_bottom_up"].mean(), "rmse_median": location["rmse_bottom_up"].median(), "bias_mean": location["bias_bottom_up"].mean(), "pct_rmse_wins": round(100 * location_win, 1)},
            {"level": "location", "method": "top_down", "n_series": len(location), "rmse_mean": location["rmse_top_down"].mean(), "rmse_median": location["rmse_top_down"].median(), "bias_mean": location["bias_top_down"].mean(), "pct_rmse_wins": round(100 * (1 - location_win), 1)},
        ]
    )
    method_comparison.to_csv(OUTPUT_DIR / "method_comparison.csv", index=False)
    print("\n=== method_comparison.csv ===")
    print(method_comparison.to_string(index=False))
