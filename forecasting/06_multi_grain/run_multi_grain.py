# %% [markdown]
# # Multi-grain / ADIDA backtest (Strategy 3 — Step C)
#
# Two things, per `05`'s recommendation and `04`'s own "fast follow" suggestion:
#
# 1. **Re-run the ADI/CV² classification at weekly grain** — confirm empirically
#    whether a real Smooth/Erratic segment emerges once the catalog is
#    aggregated to a coarser time bucket, rather than assuming it does.
# 2. **ADIDA**: forecast SBA (carried forward from `05` — it strictly beat raw
#    Croston there) at weekly grain, disaggregate uniformly back to daily, and
#    compare against `05`'s native daily-grain SBA on the *same* daily holdout
#    — does aggregating across time before forecasting actually lift accuracy,
#    or does `05`'s per-series-vs-portfolio divergence show up here too.
#
# See `06_multi_grain_summary.md` for the write-up; this script produces the
# numbers behind it.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_granularity_baselines"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04_demand_classification"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "05_croston_sba"))

import numpy as np
import pandas as pd

from _shared.db_connection import query_df
from run_baselines import most_recent_complete_year, compute_metrics
from classify_demand_patterns import compute_series_stats, classify_category, ADI_THRESHOLD, CV2_THRESHOLD
from run_croston_sba import croston_sba, ALPHA

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MARTS_SCRATCH = "develop.eros_analytics_forecasting_scratch.fact_demand_daily"
UPSTREAM_WEEKLY_CACHE = Path(__file__).resolve().parents[1] / "03_granularity_baselines" / "output" / "_fact_demand_weekly.parquet"
DAILY_SBA_FORECASTS = Path(__file__).resolve().parents[1] / "05_croston_sba" / "output" / "_croston_sba_forecasts.parquet"
DAILY_CLASSIFICATION_CSV = Path(__file__).resolve().parents[1] / "04_demand_classification" / "output" / "demand_classification.csv"

KEYS = ["product_variant_id", "location_id"]

# %% [markdown]
# ## 1. Load weekly series (reuse `03`'s cached weekly rollup — never
# reprocessing `fct_sales` or even `fact_demand_daily` directly).

# %%
def load_weekly() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_fact_demand_weekly.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    if UPSTREAM_WEEKLY_CACHE.exists():
        df = pd.read_parquet(UPSTREAM_WEEKLY_CACHE)
    else:
        df = query_df(
            f"""
            select date_trunc('week', date_day) as period, {', '.join(KEYS)}, sum(qty_sold_net) as qty_sold_net
            from {MARTS_SCRATCH} group by 1, 2, 3
            """
        )
        df["period"] = pd.to_datetime(df["period"]).dt.tz_localize(None)
        df["qty_sold_net"] = df["qty_sold_net"].astype("float32")
        for k in KEYS:
            df[k] = df[k].astype(str)

    df.to_parquet(cache_path)
    return df


# %% [markdown]
# ## 2. Weekly-grain ADI/CV² reclassification — same thresholds and same
# `compute_series_stats`/`classify_category` reused verbatim from `04`
# (left-trimmed to each series' own first non-zero week, same rationale).

# %%
def classify_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(KEYS + ["period"])
    records = []
    for keys, g in df.groupby(KEYS, sort=False):
        stats = compute_series_stats(g["qty_sold_net"].to_numpy())
        records.append({"product_variant_id": keys[0], "location_id": keys[1], **stats})
    return pd.DataFrame(records)


# %% [markdown]
# ## 3. ADIDA — SBA at weekly grain (reusing `05`'s `croston_sba`, same
# left-trim, same alpha), then uniform disaggregation back to daily
# (`weekly_forecast / 7`, no intra-week seasonal profile — the simplest
# defensible ADIDA disaggregation when no day-of-week profile has been
# validated separately). No lookahead, same sequential discipline as `05`.

# %%
def run_sba_for_series(df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    df = df.sort_values(KEYS + ["period"])
    frames = []
    for keys, g in df.groupby(KEYS, sort=False):
        qty = g["qty_sold_net"].to_numpy()
        nonzero_idx = np.nonzero(qty)[0]
        if len(nonzero_idx) == 0:
            continue
        trimmed = g.iloc[nonzero_idx[0]:].copy()
        _, sba_pred = croston_sba(trimmed["qty_sold_net"].to_numpy(), alpha=ALPHA)
        trimmed[pred_col] = sba_pred
        frames.append(trimmed)
    return pd.concat(frames, ignore_index=True)


def disaggregate_to_daily(weekly_forecasts: pd.DataFrame) -> pd.DataFrame:
    """Explode each week's forecast into its 7 calendar days, forecast/7 each."""
    rows = weekly_forecasts.loc[weekly_forecasts["adida_pred_weekly"].notna(), KEYS + ["period", "adida_pred_weekly"]]
    exploded = rows.loc[rows.index.repeat(7)].copy()
    day_offset = np.tile(np.arange(7), len(rows))
    exploded["period"] = exploded["period"].to_numpy() + day_offset.astype("timedelta64[D]")
    exploded["adida_pred_daily"] = exploded["adida_pred_weekly"] / 7.0
    return exploded[KEYS + ["period", "adida_pred_daily"]]


# %% [markdown]
# ## 4. Metrics — daily-grain comparison against `05`'s native daily SBA
# (same holdout year, same `compute_metrics`), plus the weekly-grain SBA's
# own native accuracy for context.

# %%
def summarize_by_series(df: pd.DataFrame, actual_col: str, pred_col: str, label: str) -> pd.DataFrame:
    rows = []
    for keys, g in df.groupby(KEYS):
        m = compute_metrics(g[actual_col], g[pred_col])
        rows.append({"product_variant_id": keys[0], "location_id": keys[1], "method": label, **m})
    return pd.DataFrame(rows)


# %%
if __name__ == "__main__":
    t0 = time.time()
    weekly = load_weekly()
    print(f"loaded {len(weekly):,} weekly rows, {weekly.groupby(KEYS).ngroups:,} series")

    # --- Part 1: weekly-grain reclassification ---
    weekly_stats = classify_weekly(weekly)
    weekly_stats["category"] = weekly_stats.apply(classify_category, axis=1)
    weekly_stats.to_csv(OUTPUT_DIR / "weekly_classification.csv", index=False)

    total_volume = weekly_stats["total_qty_sold_net"].sum()
    weekly_category_summary = (
        weekly_stats.groupby("category").agg(n_series=("category", "size"), total_qty=("total_qty_sold_net", "sum")).reset_index()
    )
    weekly_category_summary["pct_series"] = round(100 * weekly_category_summary["n_series"] / len(weekly_stats), 1)
    weekly_category_summary["pct_volume"] = round(100 * weekly_category_summary["total_qty"] / total_volume, 1) if total_volume else 0.0
    weekly_category_summary = weekly_category_summary.sort_values("n_series", ascending=False)
    weekly_category_summary.to_csv(OUTPUT_DIR / "weekly_category_summary.csv", index=False)
    print(f"\nWeekly-grain classification (ADI thresh={ADI_THRESHOLD}, CV2 thresh={CV2_THRESHOLD}):")
    print(weekly_category_summary.to_string(index=False))

    # --- Part 2: ADIDA weekly SBA + disaggregation ---
    weekly_forecasts_path = OUTPUT_DIR / "_adida_weekly_forecasts.parquet"
    if weekly_forecasts_path.exists():
        weekly_forecasted = pd.read_parquet(weekly_forecasts_path)
    else:
        weekly_forecasted = run_sba_for_series(weekly, "adida_pred_weekly")
        weekly_forecasted.to_parquet(weekly_forecasts_path)
    print(f"\nWeekly SBA state machine run in {time.time() - t0:.1f}s")

    holdout_year_weekly = most_recent_complete_year(weekly_forecasted["period"], "weekly")
    holdout_weekly = weekly_forecasted[weekly_forecasted["period"].dt.year == holdout_year_weekly].copy()
    weekly_native_metrics = summarize_by_series(holdout_weekly, "qty_sold_net", "adida_pred_weekly", "sba_weekly_native")
    weekly_native_metrics.to_csv(OUTPUT_DIR / "adida_weekly_native_metrics.csv", index=False)

    disaggregated = disaggregate_to_daily(weekly_forecasted)

    daily_sba = pd.read_parquet(DAILY_SBA_FORECASTS)[KEYS + ["period", "qty_sold_net", "sba_pred"]]
    holdout_year_daily = most_recent_complete_year(daily_sba["period"], "daily")

    combined = daily_sba.merge(disaggregated, on=KEYS + ["period"], how="left")
    holdout_daily = combined[combined["period"].dt.year == holdout_year_daily].copy()
    print(f"\ndaily holdout year: {holdout_year_daily}, weekly holdout year: {holdout_year_weekly}")

    per_series_daily_sba = summarize_by_series(holdout_daily, "qty_sold_net", "sba_pred", "daily_sba_native")
    per_series_adida = summarize_by_series(holdout_daily, "qty_sold_net", "adida_pred_daily", "adida_disaggregated")
    per_series_comparison = pd.concat([per_series_daily_sba, per_series_adida], ignore_index=True)
    per_series_comparison.to_csv(OUTPUT_DIR / "adida_daily_metrics.csv", index=False)

    # --- by demand-pattern category (04's daily-grain routing labels) ---
    classification = pd.read_csv(DAILY_CLASSIFICATION_CSV, dtype={"product_variant_id": str, "location_id": str})
    per_series_with_cat = per_series_comparison.merge(classification[KEYS + ["category"]], on=KEYS, how="left")
    category_summary = (
        per_series_with_cat.groupby(["method", "category"])
        .agg(
            n_series=("rmse", "size"),
            rmse_mean=("rmse", "mean"),
            rmse_median=("rmse", "median"),
            bias_mean=("bias", "mean"),
            smape_median=("smape", "median"),
        )
        .reset_index()
    )
    category_summary.to_csv(OUTPUT_DIR / "adida_vs_daily_sba_by_category.csv", index=False)

    # --- per-series recommendation: whichever wins on RMSE (the trustworthy
    # metric per 05's sMAPE/MAPE-saturation finding) becomes the forecast this
    # stage recommends carrying forward. ---
    wide = per_series_daily_sba.merge(
        per_series_adida, on=KEYS, suffixes=("_daily_sba", "_adida")
    )
    wide["method_chosen"] = np.where(wide["rmse_adida"] < wide["rmse_daily_sba"], "adida", "daily_sba")
    recommendation = wide[KEYS + ["rmse_daily_sba", "rmse_adida", "method_chosen"]].copy()
    recommendation["rmse_improvement_pct"] = round(
        100 * (recommendation["rmse_daily_sba"] - recommendation["rmse_adida"]) / recommendation["rmse_daily_sba"], 2
    )
    recommendation.to_csv(OUTPUT_DIR / "method_recommendation.csv", index=False)

    # --- persist the actually-recommended per-series/per-day forecast values,
    # for the hierarchical-reconciliation workstream's Bottom-Up stage to sum
    # across locations. ---
    combined_with_choice = combined.merge(recommendation[KEYS + ["method_chosen"]], on=KEYS, how="left")
    combined_with_choice["recommended_pred"] = np.where(
        combined_with_choice["method_chosen"] == "adida",
        combined_with_choice["adida_pred_daily"],
        combined_with_choice["sba_pred"],
    )
    combined_with_choice[KEYS + ["period", "qty_sold_net", "recommended_pred", "method_chosen"]].to_parquet(
        OUTPUT_DIR / "_recommended_forecasts.parquet"
    )

    n_adida_wins = int((recommendation["method_chosen"] == "adida").sum())
    print(f"\n=== Per-series RMSE win rate: ADIDA wins {n_adida_wins:,}/{len(recommendation):,} ({100*n_adida_wins/len(recommendation):.1f}%) ===")

    print("\n=== daily_sba_native vs adida_disaggregated (per-series, median across full catalog) ===")
    for label, df_m in [("daily_sba_native", per_series_daily_sba), ("adida_disaggregated", per_series_adida)]:
        print(f"  {label:22s} rmse_mean={df_m['rmse'].mean():.4f}  rmse_median={df_m['rmse'].median():.4f}  bias_mean={df_m['bias'].mean():+.4f}  smape_median={df_m['smape'].median():.4f}")

    print("\n=== weekly-grain SBA native (its own accuracy at weekly grain) ===")
    print(f"  rmse_mean={weekly_native_metrics['rmse'].mean():.4f}  rmse_median={weekly_native_metrics['rmse'].median():.4f}  bias_mean={weekly_native_metrics['bias'].mean():+.4f}  smape_median={weekly_native_metrics['smape'].median():.4f}")

    print("\n=== by demand-pattern category ===")
    print(category_summary.to_string(index=False))
