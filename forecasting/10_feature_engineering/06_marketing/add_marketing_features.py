# %% [markdown]
# # Task 2.6 -- Add marketing/promotion features
#
# Builds on task 2.5's `baseline+calendar+holidays+weather+economic` formula.
# Scoped to `stg_orders.discount_amount` only (confirmed with the team before
# this stage started): no campaign/promotion table or marketing-spend data
# exists anywhere in this project, and `discount_amount` is computed in
# staging but currently dropped before it reaches `int_sales_enriched`/
# `fct_sales`. Queried directly from `stg_orders` here -- no dbt model
# changes, consistent with this workstream's "exploratory, not a committed
# dbt model" convention.
#
# Aggregated to (location, week), not (product, location, week): an order's
# `discount_amount` is at the ORDER level, not the line-item level, and
# allocating it across an order's individual line items would need an
# arbitrary allocation rule (e.g. pro-rata by line value) this task doesn't
# need -- the causal hypothesis ("discount events lift short-term volume") is
# naturally a location-week-level signal (a store ran a promotion), broadcast
# to every product sold at that location that week, the same way weather and
# economic features are broadcast.
#
# `baseline+calendar+holidays+weather+economic` is refit here in-memory
# purely to compute this task's delta -- not re-logged (task 2.5 already
# logged it). Only the `+marketing` run is logged as new.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_holidays"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04_weather"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "05_economic"))

import numpy as np
import pandas as pd
from add_calendar_features import add_calendar_features
from add_economic_features import add_economic_features
from add_holiday_features import add_holiday_features
from add_weather_features import WEATHER_END_DATE, add_weather_features

from _shared.panel_regression import PROD_STAGING, fit_and_evaluate, init_mlflow_experiment, load_weekly_panel, query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MAPE_IMPROVEMENT_THRESHOLD = 0.02

# %% [markdown]
# ## 1. Discount features -- location x week grain
#
# Only `paid`/`confirmed` orders, matching the "valid revenue" convention
# `fact_demand_daily`/`agg_sales_daily` already use elsewhere in this
# project (`filter_valid_orders()`), so discount activity on cancelled/draft
# orders (which never became real demand) doesn't leak into the signal.


# %%
def load_discount_weekly() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_discount_raw.parquet"
    if cache_path.exists():
        orders = pd.read_parquet(cache_path)
    else:
        orders = query_df(
            f"""
            select location_id, placed_at, discount_amount, subtotal
            from {PROD_STAGING}.stg_orders
            where status in ('paid', 'confirmed')
            """
        )
        orders.to_parquet(cache_path)

    # discount_amount/subtotal come back as Python Decimal (object dtype)
    # from the Databricks SQL connector, since they're DECIMAL columns in
    # stg_orders -- cast explicitly rather than relying on downstream
    # libraries to silently coerce them (linearmodels does; plain pandas
    # arithmetic against a float64 column raises TypeError instead, which is
    # what surfaced this in task 2.9's VIF check).
    orders["discount_amount"] = orders["discount_amount"].astype("float64")
    orders["subtotal"] = orders["subtotal"].astype("float64")
    orders["placed_at"] = pd.to_datetime(orders["placed_at"]).dt.tz_localize(None)
    orders["period"] = orders["placed_at"] - pd.to_timedelta(orders["placed_at"].dt.weekday, unit="D")
    orders["period"] = orders["period"].dt.normalize()
    orders["location_id"] = orders["location_id"].astype(str)

    weekly = (
        orders.groupby(["location_id", "period"])
        .agg(total_discount_amount=("discount_amount", "sum"), total_subtotal=("subtotal", "sum"))
        .reset_index()
    )
    weekly["discount_rate"] = (weekly["total_discount_amount"] / weekly["total_subtotal"].replace(0, np.nan)).fillna(
        0.0
    )
    return weekly


def add_marketing_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    weekly_discount = load_discount_weekly()
    df = df.merge(weekly_discount, on=["location_id", "period"], how="left")
    df["total_discount_amount"] = df["total_discount_amount"].fillna(0.0)
    df["discount_rate"] = df["discount_rate"].fillna(0.0)
    # `total_discount_amount` is deliberately NOT included as a feature: it's
    # a raw sum, mechanically tied to order volume (a location-week with more
    # orders has more total discount dollars almost by definition, even at a
    # constant average discount rate), so it's really a volume/scale proxy,
    # not a causal discounting signal -- and it's collinear with
    # `discount_rate` (same numerator). An initial fit including both showed
    # exactly the red flag this project has now learned to check for: t-stats
    # around 44 for each (larger than task 2.5's pre-fix SELIC anomaly) with
    # `discount_rate` flipping sign relative to its raw correlation with
    # demand -- a scale/collinearity confound, not a genuine finding. Dropped
    # rather than reported at face value; see `06_marketing_report.md`.
    return df, ["discount_rate"]


# %% [markdown]
# ## 2. Reverse-causality check
#
# Tests whether discount weeks are timed to *already*-elevated demand (the
# marketing team reacting to expected demand) rather than driving it: does
# this week's location-level `discount_rate` correlate with *last* week's
# location-level demand? A positive correlation would mean discounts follow
# high-demand weeks rather than create them -- the reverse of the causal
# story this feature is meant to test.


# %%
def check_reverse_causality(df: pd.DataFrame) -> dict:
    location_weekly = (
        df.groupby(["location_id", "period"])
        .agg(qty_sold_net=("qty_sold_net", "sum"), discount_rate=("discount_rate", "first"))
        .reset_index()
        .sort_values(["location_id", "period"])
    )
    location_weekly["qty_sold_net_lag1"] = location_weekly.groupby("location_id")["qty_sold_net"].shift(1)
    valid = location_weekly.dropna(subset=["qty_sold_net_lag1"])
    contemporaneous_corr = valid["discount_rate"].corr(valid["qty_sold_net"])
    lagged_corr = valid["discount_rate"].corr(valid["qty_sold_net_lag1"])
    return {
        "contemporaneous_corr_discount_vs_demand": contemporaneous_corr,
        "lagged_corr_discount_vs_prior_week_demand": lagged_corr,
        "n_location_weeks": len(valid),
    }


# %% [markdown]
# ## 3. MLflow logging (new run only)


# %%
def log_run(mlflow, run: dict, feature_cols: list[str], cumulative_features: str):
    with mlflow.start_run(run_name=run["run_name"]) as mlflow_run:
        mlflow.set_tags(
            {
                "phase": "2_feature_engineering",
                "task_ids": "2.6",
                "grain": "product_variant_id x location_id (SKU x Store) x ISO week",
                "source": "forecasting/10_feature_engineering/06_marketing",
                "data_source": f"{PROD_STAGING}.stg_orders (discount_amount)",
                "formula": "+".join(["entity_fe"] + feature_cols),
            }
        )
        mlflow.log_params(
            {
                "cumulative_features": cumulative_features,
                "holdout_year": run["holdout_year"],
                "n_feature_cols": len(feature_cols),
                "estimator": "PanelOLS(entity_effects=True)",
                "target": "log1p(qty_sold_net)",
                "marketing_scope": "discount_amount only -- no campaign/spend data exists in the project",
            }
        )
        for metric, value in run["metrics"].items():
            if isinstance(value, (int, float)) and not pd.isna(value):
                mlflow.log_metric(metric, float(value))
        print(f"Logged run '{run['run_name']}' -> run_id={mlflow_run.info.run_id}")


# %% [markdown]
# ## 4. Fit previous formula (not re-logged) and `+marketing`, compare
# against the >2% MAPE threshold, plus the reverse-causality check

# %%
if __name__ == "__main__":
    cache_path = Path(__file__).resolve().parents[1] / "02_calendar" / "output" / "_weekly_panel.parquet"
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        panel = load_weekly_panel()
        panel.to_parquet(cache_path)

    panel = panel[panel["period"] <= WEATHER_END_DATE].copy()

    panel, calendar_cols = add_calendar_features(panel)
    panel, holiday_cols = add_holiday_features(panel)
    panel, weather_cols = add_weather_features(panel)
    panel, economic_cols = add_economic_features(panel)
    panel, marketing_cols = add_marketing_features(panel)

    reverse_causality = check_reverse_causality(panel)
    print("Reverse-causality check:", reverse_causality)
    pd.Series(reverse_causality).to_csv(OUTPUT_DIR / "reverse_causality_check.csv")

    prior_cols = calendar_cols + holiday_cols + weather_cols + economic_cols
    previous_run = fit_and_evaluate(panel, prior_cols, "baseline+calendar+holidays+weather+economic")
    marketing_run = fit_and_evaluate(
        panel, prior_cols + marketing_cols, "baseline+calendar+holidays+weather+economic+marketing"
    )

    print(f"Holdout year: {marketing_run['holdout_year']}")
    print("previous metrics:", previous_run["metrics"])
    print("+marketing metrics:", marketing_run["metrics"])

    prev_mape = previous_run["metrics"]["mape"]
    new_mape = marketing_run["metrics"]["mape"]
    mape_improvement = (prev_mape - new_mape) / prev_mape
    meets_threshold = mape_improvement > MAPE_IMPROVEMENT_THRESHOLD
    print(f"MAPE improvement vs. previous formula: {mape_improvement:.2%} (threshold: >{MAPE_IMPROVEMENT_THRESHOLD:.0%})")
    print(f"Meets threshold: {meets_threshold}")

    coef_table = pd.DataFrame(
        {
            "coefficient": marketing_run["result"].params,
            "std_error": marketing_run["result"].std_errors,
            "t_stat": marketing_run["result"].tstats,
            "p_value": marketing_run["result"].pvalues,
        }
    )
    coef_table.to_csv(OUTPUT_DIR / "coefficients.csv")

    metrics_comparison = pd.DataFrame(
        {"previous": previous_run["metrics"], "+marketing": marketing_run["metrics"]}
    )
    metrics_comparison["pct_change"] = (
        metrics_comparison["+marketing"] - metrics_comparison["previous"]
    ) / metrics_comparison["previous"]
    metrics_comparison.to_csv(OUTPUT_DIR / "metrics_comparison.csv")

    with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
        f.write(
            f"mape_improvement={mape_improvement:.4f}\n"
            f"threshold={MAPE_IMPROVEMENT_THRESHOLD}\n"
            f"meets_threshold={meets_threshold}\n"
        )

    mlflow = init_mlflow_experiment()
    log_run(mlflow, marketing_run, prior_cols + marketing_cols, "calendar+holidays+weather+economic+marketing")
