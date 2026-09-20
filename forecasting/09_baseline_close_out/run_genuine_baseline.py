# %% [markdown]
# # Task 1.3/1.4/1.6/1.7/1.8 close-out — 3-month-ahead baseline, held static
#
# Computes the Moving Average level **once per cutoff**, holds it flat for the
# full agreed ~91-day (3-month) horizon, and scores it across multiple rolling
# origins (task 1.6), so the forecast never sees demand from inside the window
# it is scored on (a level recomputed every day would, as in `08`'s 15/30-day
# windows). Seasonal Naive is scored the same way. See
# `09_baseline_close_out_summary.md` for the write-up.
#
# Data source and grain: `fct_sales` in the shared prod marts at
# product_variant_id x location_id, with Moving Average (28d) and Seasonal
# Naive as the two baselines.

# %%
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_granularity_baselines"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _shared.db_connection import PROD_MARTS, query_df  # noqa: E402
from run_baselines import compute_metrics  # noqa: E402  (reused verbatim, see 03/04/05/06/07 for the same convention)
from walk_forward import make_periodic_cutoffs  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MARTS = PROD_MARTS  # same source as 08
KEYS = ["product_variant_id", "location_id"]
MA_WINDOW = 28
HORIZON_DAYS = 91  # the agreed ~3-month horizon (task 1.2)
TRAIN_END = pd.Timestamp("2024-12-31")
VALIDATE_END = pd.Timestamp("2025-12-31")

SALES = f"""
vendas AS (
    SELECT s.product_variant_id, s.location_id, DATE(s.placed_at) AS dia, s.quantity
    FROM {MARTS}.fct_sales AS s
    WHERE s.order_status IN ('paid', 'confirmed')
)"""

# %% [markdown]
# ## 1. Peak season, derived independently from this data source's train period
#
# Method: average monthly total per calendar month over the train years only
# (no validation-year leakage), flagged "peak" where above the overall monthly
# average.

# %%
monthly_totals = query_df(f"""
    WITH {SALES}
    SELECT MONTH(dia) AS month, YEAR(dia) AS year, SUM(quantity) AS total_qty
    FROM vendas WHERE dia <= DATE'{TRAIN_END.date()}'
    GROUP BY MONTH(dia), YEAR(dia)
""")
avg_by_month = monthly_totals.groupby("month")["total_qty"].mean()
peak_months = sorted(avg_by_month[avg_by_month > avg_by_month.mean()].index.tolist())
print(f"Peak-season months (independently derived from {MARTS}): {peak_months}")


def compute_metrics_peak_season(actual: pd.Series, pred: pd.Series, period: pd.Series) -> dict:
    is_peak = period.dt.month.isin(peak_months)
    return compute_metrics(actual[is_peak], pred[is_peak])


# %% [markdown]
# ## 2. Cutoffs -- multiple rolling origins across the 2025 validation year (task 1.6)

# %%
cutoffs = make_periodic_cutoffs(TRAIN_END, VALIDATE_END, horizon=HORIZON_DAYS, step=HORIZON_DAYS, freq="D")
print(f"Walk-forward cutoffs ({len(cutoffs)}): {[c.date() for c in cutoffs]}")

# %% [markdown]
# ## 3. Forecast functions
#
# Moving Average: level computed once per cutoff from the 28 days immediately
# before it and held flat for the whole horizon, so it never sees demand from
# inside the window it is scored on. Seasonal Naive: joins on the real calendar
# date one year earlier. Together they cover both mandated baselines (1.3, 1.4).


# %%
def moving_average_forecast(cutoff: pd.Timestamp, horizon: int) -> pd.DataFrame:
    train_start = cutoff - pd.Timedelta(days=MA_WINDOW - 1)
    sql = f"""
    WITH {SALES},
    pairs AS (SELECT DISTINCT {", ".join(KEYS)} FROM vendas),
    cal AS (SELECT date_day AS dia FROM {MARTS}.dim_calendary
            WHERE date_day BETWEEN DATE'{train_start.date()}' AND DATE'{cutoff.date()}'),
    actuals AS (SELECT {", ".join(KEYS)}, dia, SUM(quantity) AS q FROM vendas
                WHERE dia BETWEEN DATE'{train_start.date()}' AND DATE'{cutoff.date()}'
                GROUP BY {", ".join(KEYS)}, dia),
    dense AS (
        SELECT p.*, c.dia, COALESCE(a.q, 0) AS q
        FROM pairs p CROSS JOIN cal c
        LEFT JOIN actuals a ON {" AND ".join(f"p.{k} = a.{k}" for k in KEYS)} AND c.dia = a.dia
    )
    SELECT {", ".join(KEYS)}, AVG(q) * {horizon} AS pred
    FROM dense GROUP BY {", ".join(KEYS)}
    """
    level = query_df(sql)
    horizon_period = pd.date_range(cutoff, periods=2, freq=f"{horizon}D")[1]  # single point: the whole window
    level["period"] = horizon_period
    return level[KEYS + ["period", "pred"]]


def seasonal_naive_forecast(cutoff: pd.Timestamp, horizon: int) -> pd.DataFrame:
    """A series with zero sales in the year-ago window is a legitimate
    prediction of 0, not a missing one -- pairs is the full series universe so
    that case gets a real 0 row rather than silently dropping out."""
    window_end = pd.date_range(cutoff, periods=2, freq=f"{horizon}D")[1] - pd.Timedelta(days=1)
    sql = f"""
    WITH {SALES},
    pairs AS (SELECT DISTINCT {", ".join(KEYS)} FROM vendas),
    lastyear AS (
        SELECT {", ".join(KEYS)}, SUM(quantity) AS q
        FROM vendas
        WHERE dia BETWEEN ADD_MONTHS(DATE'{(cutoff + pd.Timedelta(days=1)).date()}', -12)
                      AND ADD_MONTHS(DATE'{window_end.date()}', -12)
        GROUP BY {", ".join(KEYS)}
    )
    SELECT p.{KEYS[0]}, p.{KEYS[1]}, COALESCE(l.q, 0) AS pred
    FROM pairs p LEFT JOIN lastyear l ON {" AND ".join(f"p.{k} = l.{k}" for k in KEYS)}
    """
    pred = query_df(sql)
    pred["period"] = pd.date_range(cutoff, periods=2, freq=f"{horizon}D")[1]
    return pred[KEYS + ["period", "pred"]]


def actuals_for_window(cutoff: pd.Timestamp, horizon: int) -> pd.DataFrame:
    start, end = cutoff + pd.Timedelta(days=1), pd.date_range(cutoff, periods=2, freq=f"{horizon}D")[1] - pd.Timedelta(days=1)
    sql = f"""
    WITH {SALES}
    SELECT {", ".join(KEYS)}, SUM(quantity) AS actual
    FROM vendas WHERE dia BETWEEN DATE'{start.date()}' AND DATE'{end.date()}'
    GROUP BY {", ".join(KEYS)}
    """
    df = query_df(sql)
    df["period"] = pd.date_range(cutoff, periods=2, freq=f"{horizon}D")[1]
    return df[KEYS + ["period", "actual"]]


# %% [markdown]
# ## 4. Score both baselines across all cutoffs

# %%
BASELINES = {"moving_average": moving_average_forecast, "seasonal_naive": seasonal_naive_forecast}

overall_rows, peak_rows, portfolio_rows = [], [], []
for name, forecast_fn in BASELINES.items():
    fold_frames = []
    for cutoff in cutoffs:
        pred = forecast_fn(cutoff, HORIZON_DAYS)
        actual = actuals_for_window(cutoff, HORIZON_DAYS)
        merged = actual.merge(pred, on=KEYS + ["period"], how="left")
        merged["cutoff"] = cutoff
        fold_frames.append(merged)
    scored = pd.concat(fold_frames, ignore_index=True)

    per_group_overall = scored.groupby(KEYS + ["cutoff"]).apply(
        lambda g: pd.Series(compute_metrics(g["actual"], g["pred"])), include_groups=False
    )
    per_group_peak = scored.groupby(KEYS + ["cutoff"]).apply(
        lambda g: pd.Series(compute_metrics_peak_season(g["actual"], g["pred"], g["period"])), include_groups=False
    )
    portfolio = scored.groupby("cutoff").agg(actual_total=("actual", "sum"), forecast_total=("pred", "sum"))
    portfolio["bias"] = portfolio["actual_total"] - portfolio["forecast_total"]
    abs_error_by_cutoff = scored.assign(abs_error=(scored["actual"] - scored["pred"]).abs()).groupby("cutoff")["abs_error"].sum()
    portfolio["wape_pct"] = 100 * abs_error_by_cutoff / portfolio["actual_total"]
    portfolio.insert(0, "baseline", name)

    overall_rows.append({"baseline": name, **per_group_overall.mean().to_dict()})
    peak_rows.append({"baseline": name, **per_group_peak.mean().to_dict()})
    portfolio_rows.append(portfolio.reset_index())

overall_metrics = pd.DataFrame(overall_rows)
peak_season_metrics = pd.DataFrame(peak_rows)
portfolio_metrics = pd.concat(portfolio_rows, ignore_index=True)

print("\n=== Overall (per-series-per-fold, averaged; n=1 per group so RMSE reduces to mean absolute error) ===")
print(overall_metrics.to_string(index=False))
print("\n=== Peak season only ===")
print(peak_season_metrics.to_string(index=False))
print("\n=== Portfolio (summed across all series per fold) ===")
print(portfolio_metrics.to_string(index=False))

overall_metrics.to_csv(OUTPUT_DIR / "genuine_baseline_metrics_overall.csv", index=False)
peak_season_metrics.to_csv(OUTPUT_DIR / "genuine_baseline_metrics_peak_season.csv", index=False)
portfolio_metrics.to_csv(OUTPUT_DIR / "genuine_baseline_metrics_portfolio.csv", index=False)

# %%
if __name__ == "__main__":
    print("\nMetrics written to output/genuine_baseline_metrics_{overall,peak_season,portfolio}.csv")
