# %% [markdown]
# # Granularity comparison: Seasonal Naive vs. Moving Average vs. SES
#
# Full-catalog, exploratory backtest over the `fact_demand_daily` prototype
# (rolled up to weekly/monthly via SQL, not by reprocessing `fct_sales`).
# Baselines only — no regression/ML model. See `03_granularity_comparison_report.md`
# for the write-up; this script produces the numbers behind it.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from _shared.db_connection import get_scratch_schema, query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MARTS_SCRATCH = f"{get_scratch_schema()}.fact_demand_daily"

KEYS = ["product_variant_id", "location_id"]
SES_ALPHA = 0.3
MA_WINDOWS = {"daily": 28, "weekly": 4, "monthly": 3}

# %% [markdown]
# ## 1. Load daily/weekly/monthly series (weekly/monthly rolled up in SQL from
# the daily prototype table — never touching `fct_sales` again).

# %%
def load_granularity(granularity: str) -> pd.DataFrame:
    cache_path = OUTPUT_DIR / f"_fact_demand_{granularity}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    if granularity == "daily":
        df = query_df(f"select date_day as period, {', '.join(KEYS)}, qty_sold_net from {MARTS_SCRATCH}")
    elif granularity == "weekly":
        df = query_df(
            f"""
            select date_trunc('week', date_day) as period, {', '.join(KEYS)}, sum(qty_sold_net) as qty_sold_net
            from {MARTS_SCRATCH} group by 1, 2, 3
            """
        )
    elif granularity == "monthly":
        df = query_df(
            f"""
            select date_trunc('month', date_day) as period, {', '.join(KEYS)}, sum(qty_sold_net) as qty_sold_net
            from {MARTS_SCRATCH} group by 1, 2, 3
            """
        )
    else:
        raise ValueError(granularity)

    df["period"] = pd.to_datetime(df["period"]).dt.tz_localize(None)
    df["qty_sold_net"] = df["qty_sold_net"].astype("float32")
    for k in KEYS:
        df[k] = df[k].astype(str)
    df.to_parquet(cache_path)
    return df


# %% [markdown]
# ## 2. Baselines — each forecasts period *t* using only data through *t-1*
# (no lookahead).

# %%
def add_moving_average(df: pd.DataFrame, window: int) -> pd.DataFrame:
    df = df.sort_values(KEYS + ["period"])
    grouped_qty = df.groupby(KEYS)["qty_sold_net"]
    # rolling mean over [t-window, t] per series, then shift(1) so the
    # forecast for t only uses [t-window, t-1] — rolling()/ewm() include the
    # current row by default, which would leak the actual value into its own
    # forecast if not shifted.
    rolling_mean = grouped_qty.rolling(window, min_periods=1).mean().reset_index(level=KEYS, drop=True)
    df["ma_pred"] = rolling_mean.groupby([df[k] for k in KEYS]).shift(1)
    return df


def add_ses(df: pd.DataFrame, alpha: float) -> pd.DataFrame:
    df = df.sort_values(KEYS + ["period"])
    ewm_mean = df.groupby(KEYS)["qty_sold_net"].transform(lambda s: s.ewm(alpha=alpha, adjust=False).mean())
    df["ses_pred"] = ewm_mean.groupby([df[k] for k in KEYS]).shift(1)
    return df


def add_seasonal_naive(df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    """forecast(t) = actual value at the same calendar period one year prior.

    Joined on real dates (t - 1 year), never an integer day-of-year, since
    day-of-year misaligns by a day across leap years (2020, 2024 both fall in
    this dataset's range).
    """
    lookup = df[KEYS + ["period", "qty_sold_net"]].rename(columns={"qty_sold_net": "seasonal_naive_pred"})

    if granularity == "monthly":
        # month-start dates: year-1, same month — exact, no ambiguity.
        prior = df["period"] - pd.DateOffset(years=1)
    elif granularity == "weekly":
        # snap (period - 1yr) to that week's Monday, since our weeks are
        # Monday-anchored (date_trunc('week', ...) in Spark SQL is ISO/Monday).
        shifted = df["period"] - pd.DateOffset(years=1)
        prior = shifted - pd.to_timedelta(shifted.dt.weekday, unit="D")
    else:  # daily
        prior = df["period"] - pd.DateOffset(years=1)

    df = df.copy()
    df["_prior_period"] = prior
    merged = df.merge(
        lookup,
        left_on=KEYS + ["_prior_period"],
        right_on=KEYS + ["period"],
        how="left",
        suffixes=("", "_prioryear"),
    )
    merged = merged.drop(columns=["_prior_period", "period_prioryear"])
    return merged


# %% [markdown]
# ## 3. Metrics — RMSE, Bias, MAPE (zero-actual rows excluded, % reported),
# sMAPE (reported alongside MAPE since it stays defined at zero-actual).

# %%
def compute_metrics(actual: pd.Series, pred: pd.Series) -> dict:
    valid = pred.notna()
    n_total = len(actual)
    n_valid = int(valid.sum())
    a, p = actual[valid], pred[valid]
    error = a - p

    rmse = float(np.sqrt(np.mean(error**2))) if n_valid else np.nan
    bias = float(error.mean()) if n_valid else np.nan

    nonzero_actual = a != 0
    n_mape_rows = int(nonzero_actual.sum())
    mape = float((error[nonzero_actual].abs() / a[nonzero_actual].abs()).mean()) if n_mape_rows else np.nan

    denom = a.abs() + p.abs()
    smape_terms = np.where(denom == 0, 0.0, 2 * error.abs() / denom.replace(0, np.nan))
    smape = float(np.nanmean(smape_terms)) if n_valid else np.nan

    return {
        "n_total_rows": n_total,
        "n_forecastable_rows": n_valid,
        "pct_forecastable": round(100 * n_valid / n_total, 1) if n_total else np.nan,
        "n_mape_rows_nonzero_actual": n_mape_rows,
        "pct_excluded_from_mape_zero_actual": round(100 * (n_valid - n_mape_rows) / n_valid, 1) if n_valid else np.nan,
        "rmse": rmse,
        "bias": bias,
        "mape": mape,
        "smape": smape,
    }


# %% [markdown]
# ## 4. Run all granularity x baseline combinations, full catalog + portfolio total

# %%
def most_recent_complete_year(periods: pd.Series, granularity: str) -> int:
    """A year is "complete" if its December is fully present in the data.

    Period values are period *starts* (month-start for monthly, Monday for
    weekly), so a naive "period >= Dec 25" check only works for daily grain —
    a monthly period for December is always literally `Dec 1`.
    """
    years_present = sorted(periods.dt.year.unique())

    def _is_complete(year: int) -> bool:
        year_periods = periods[periods.dt.year == year]
        if granularity == "monthly":
            return 12 in year_periods.dt.month.values
        if granularity == "weekly":
            return bool((year_periods >= pd.Timestamp(year, 12, 24)).any())
        return bool((year_periods >= pd.Timestamp(year, 12, 25)).any())

    complete_years = [y for y in years_present if _is_complete(y)]
    return max(complete_years)


def run_granularity(granularity: str, results_detail: list, results_portfolio: list):
    print(f"\n=== {granularity} ===")
    t0 = time.time()
    df = load_granularity(granularity)

    holdout_year = most_recent_complete_year(df["period"], granularity)
    train_start_year = df["period"].dt.year.min()
    print(f"  train years: {train_start_year}-{holdout_year - 1}, holdout year: {holdout_year} (partial current year excluded)")

    df = add_moving_average(df, MA_WINDOWS[granularity])
    df = add_ses(df, SES_ALPHA)
    df = add_seasonal_naive(df, granularity)
    print(f"  baselines computed in {time.time() - t0:.1f}s")

    holdout = df[df["period"].dt.year == holdout_year].copy()

    # --- per-series metrics, aggregated to one row per (granularity, baseline) ---
    for baseline, col in [("seasonal_naive", "seasonal_naive_pred"), ("moving_average", "ma_pred"), ("ses", "ses_pred")]:
        # per-series metrics first (so we can report a distribution, not just
        # a pooled mean that full-catalog outliers would skew)
        per_series_rows = []
        for keys, g in holdout.groupby(KEYS):
            m = compute_metrics(g["qty_sold_net"], g[col])
            per_series_rows.append({"product_variant_id": keys[0], "location_id": keys[1], **m})
        per_series_df = pd.DataFrame(per_series_rows)

        summary = {
            "granularity": granularity,
            "baseline": baseline,
            "n_series": len(per_series_df),
            "n_series_fully_excluded": int((per_series_df["n_forecastable_rows"] == 0).sum()),
            "pct_series_fully_excluded": round(100 * (per_series_df["n_forecastable_rows"] == 0).mean(), 1),
            "rmse_mean": per_series_df["rmse"].mean(),
            "rmse_median": per_series_df["rmse"].median(),
            "bias_mean": per_series_df["bias"].mean(),
            "mape_mean": per_series_df["mape"].mean(),
            "mape_median": per_series_df["mape"].median(),
            "smape_mean": per_series_df["smape"].mean(),
            "smape_median": per_series_df["smape"].median(),
            "avg_pct_excluded_from_mape_zero_actual": per_series_df["pct_excluded_from_mape_zero_actual"].mean(),
        }
        results_detail.append(summary)
        print(f"  {baseline:16s} sMAPE(median)={summary['smape_median']:.3f}  MAPE(median)={summary['mape_median']:.3f}  RMSE(mean)={summary['rmse_mean']:.2f}  Bias(mean)={summary['bias_mean']:+.3f}  excluded_series={summary['pct_series_fully_excluded']}%")

    # --- whole-portfolio total (sum across all series per period) as a sanity upper bound ---
    portfolio = df.groupby("period", as_index=False).agg(
        qty_sold_net=("qty_sold_net", "sum"),
        ma_pred=("ma_pred", "sum"),
        ses_pred=("ses_pred", "sum"),
        seasonal_naive_pred=("seasonal_naive_pred", "sum"),
    )
    portfolio_holdout = portfolio[portfolio["period"].dt.year == holdout_year]
    for baseline, col in [("seasonal_naive", "seasonal_naive_pred"), ("moving_average", "ma_pred"), ("ses", "ses_pred")]:
        m = compute_metrics(portfolio_holdout["qty_sold_net"], portfolio_holdout[col])
        results_portfolio.append({"granularity": granularity, "baseline": baseline, **m})


# %%
if __name__ == "__main__":
    detail_rows: list = []
    portfolio_rows: list = []
    for gran in ["daily", "weekly", "monthly"]:
        run_granularity(gran, detail_rows, portfolio_rows)

    summary_df = pd.DataFrame(detail_rows)
    summary_df.to_csv(OUTPUT_DIR / "metrics_by_granularity_baseline.csv", index=False)

    portfolio_df = pd.DataFrame(portfolio_rows)
    portfolio_df.to_csv(OUTPUT_DIR / "portfolio_total_metrics.csv", index=False)

    print("\n\n=== Summary (per-series, median across full catalog) ===")
    print(summary_df[["granularity", "baseline", "smape_median", "mape_median", "rmse_mean", "bias_mean", "pct_series_fully_excluded"]].to_string(index=False))

    print("\n=== Whole-portfolio total (sanity upper bound) ===")
    print(portfolio_df[["granularity", "baseline", "smape", "mape", "rmse", "bias"]].to_string(index=False))
