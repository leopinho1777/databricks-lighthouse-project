# %% [markdown]
# # Task 2.7 -- Add internal/inventory features
#
# Builds on task 2.6's `baseline+calendar+holidays+weather+economic+marketing`
# formula.
#
# Two exclusions decided before fitting anything, for two DIFFERENT reasons
# (kept distinct deliberately -- conflating them would misrepresent what was
# actually checked):
#
# 1. **`is_demand_censored_flag` is target leakage, not a confound, and is not
#    fit as a regression feature at all.** Per
#    `02_schema_design/fact_demand_daily_prototype.sql:125`:
#    `is_demand_censored_flag = coalesce(qty_sold_gross, 0) >= stock_on_hand`
#    -- it is computed directly from the SAME day's `qty_sold_gross`, which is
#    (up to returns) this task's own target variable. A model fit with this as
#    a regressor could look informative purely because it partially encodes
#    the answer, and it would be unusable in deployment anyway: next week's
#    actual `qty_sold_net` is never available ahead of time to compute it
#    from. This is categorically different from a confound (an external
#    variable that happens to correlate with the target through some
#    mechanism, like the SELIC/trend or discount/volume cases in tasks 2.5-2.6)
#    -- it doesn't produce a "suspicious t-stat" a post-hoc check can catch,
#    it's simply not a valid input, so it is excluded outright rather than
#    tested and reported as "not significant." It IS reported below as a
#    descriptive/diagnostic statistic (what fraction of weeks are flagged),
#    which is valid context, just not a regression term.
# 2. **Price-change is dropped for data-availability reasons** (confirmed in
#    `00_feature_backlog.md`): `dim_products` has only a single current price
#    per variant, no price history anywhere in the project. Distinct from
#    reason 1 above -- even if price history existed, a current-price feature
#    would carry its own, different problem (joint determination/endogeneity:
#    price and demand are set simultaneously, so the causal direction between
#    them is genuinely ambiguous), not a target-leakage problem. Both
#    exclusions happen to remove inventory/price signals from this task, but
#    for unrelated reasons.
#
# `is_stockout_day` (`stock_on_hand == 0`, derived purely from the
# forward-filled stock snapshot series -- independent of `qty_sold_gross`/
# `qty_sold_net`) is the only new regression feature this task tests, with
# its already-documented sparse-snapshot caveat restated below.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_holidays"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04_weather"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "05_economic"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "06_marketing"))

import pandas as pd
from add_calendar_features import add_calendar_features
from add_economic_features import add_economic_features
from add_holiday_features import add_holiday_features
from add_marketing_features import add_marketing_features
from add_weather_features import WEATHER_END_DATE, add_weather_features

from _shared.panel_regression import (
    KEYS,
    MARTS_SCRATCH,
    fit_and_evaluate,
    init_mlflow_experiment,
    load_weekly_panel,
    query_df,
)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MAPE_IMPROVEMENT_THRESHOLD = 0.02

# %% [markdown]
# ## 1. Weekly stockout/censoring stats, per (product, location)


# %%
def load_inventory_weekly() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_inventory_raw.parquet"
    if cache_path.exists():
        weekly = pd.read_parquet(cache_path)
    else:
        weekly = query_df(
            f"""
            select date_trunc('week', date_day) as period, {', '.join(KEYS)},
                   avg(cast(is_stockout_day as double)) as stockout_day_fraction,
                   avg(cast(is_demand_censored_flag as double)) as censored_day_fraction
            from {MARTS_SCRATCH} group by 1, 2, 3
            """
        )
        weekly.to_parquet(cache_path)

    weekly["period"] = pd.to_datetime(weekly["period"]).dt.tz_localize(None)
    for k in KEYS:
        weekly[k] = weekly[k].astype(str)
    return weekly


MIN_ENTITIES_WITH_VARIATION = 30  # arbitrary but generous floor for a credible fixed-effects coefficient


def check_stockout_testability(weekly_inventory: pd.DataFrame) -> dict:
    """`PanelOLS(entity_effects=True)` estimates a feature's coefficient from
    WITHIN-entity variation only -- an entity whose `stockout_day_fraction`
    never changes contributes nothing to that estimate, no matter how many
    rows it has. If almost no entity ever varies, a "fit" would be driven by
    a handful of series and would not be a credible population-level
    estimate, independent of whatever p-value comes out. Computed on the raw
    (pre-fill) table so "no stock snapshot ever reached this entity" (NaN)
    is counted separately from "confirmed not stocked out" (0.0).
    """
    entities_total = weekly_inventory[list(KEYS)].drop_duplicates().shape[0]
    with_any_data = weekly_inventory.dropna(subset=["stockout_day_fraction"])
    with_variation = with_any_data[with_any_data["stockout_day_fraction"] > 0][list(KEYS)].drop_duplicates()
    return {
        "n_entities_total": entities_total,
        "n_entities_with_any_stock_data": with_any_data[list(KEYS)].drop_duplicates().shape[0],
        "n_entities_with_any_stockout": len(with_variation),
        "pct_rows_with_stock_data": 100 * weekly_inventory["stockout_day_fraction"].notna().mean(),
        "pct_rows_flagged_stockout": 100 * (weekly_inventory["stockout_day_fraction"] > 0).mean(),
    }


def add_inventory_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    weekly_inventory = load_inventory_weekly()
    df = df.merge(weekly_inventory, on=[*KEYS, "period"], how="left")
    # NaN here means no stock snapshot has ever reached this (product,
    # location) by this date, not "confirmed not stocked out" -- filling
    # with 0.0 is the same "no evidence of a stockout" convention the
    # prototype table itself uses (`coalesce(..., 0)`), applied only after
    # the testability check above has already looked at real coverage.
    df["stockout_day_fraction"] = df["stockout_day_fraction"].fillna(0.0)
    df["censored_day_fraction"] = df["censored_day_fraction"].fillna(0.0)
    # censored_day_fraction is carried through for the descriptive stat in
    # the report only -- NOT returned as a regression feature (target
    # leakage, see script header).
    return df, ["stockout_day_fraction"], weekly_inventory


# %% [markdown]
# ## 2. MLflow logging (new run only)


# %%
def log_run(mlflow, run: dict, feature_cols: list[str], cumulative_features: str):
    with mlflow.start_run(run_name=run["run_name"]) as mlflow_run:
        mlflow.set_tags(
            {
                "phase": "2_feature_engineering",
                "task_ids": "2.7",
                "grain": "product_variant_id x location_id (SKU x Store) x ISO week",
                "source": "forecasting/10_feature_engineering/07_internal_inventory",
                "data_source": MARTS_SCRATCH,
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
                "excluded_target_leakage": "is_demand_censored_flag (derived from same-day qty_sold_gross)",
                "excluded_data_unavailable": "price-change (no price-history model exists)",
            }
        )
        for metric, value in run["metrics"].items():
            if isinstance(value, (int, float)) and not pd.isna(value):
                mlflow.log_metric(metric, float(value))
        print(f"Logged run '{run['run_name']}' -> run_id={mlflow_run.info.run_id}")


# %% [markdown]
# ## 3. Fit previous formula (not re-logged) and `+inventory`, compare
# against the >2% MAPE threshold

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
    panel, inventory_cols, weekly_inventory_raw = add_inventory_features(panel)

    censored_week_pct = 100 * (panel["censored_day_fraction"] > 0).mean()
    print(f"Descriptive only (not a regression feature): {censored_week_pct:.2f}% of product-location-weeks "
          f"have at least one day flagged is_demand_censored_flag.")

    testability = check_stockout_testability(weekly_inventory_raw)
    print("Stockout testability check:", testability)
    pd.Series(testability).to_csv(OUTPUT_DIR / "testability_check.csv")
    with open(OUTPUT_DIR / "censored_demand_descriptive.txt", "w", encoding="utf-8") as f:
        f.write(f"pct_weeks_with_any_censored_day={censored_week_pct:.2f}\n")
        f.write("NOTE: is_demand_censored_flag is target leakage (derived from same-day qty_sold_gross) "
                "and was NOT used as a regression feature -- see script header comment.\n")

    prior_cols = calendar_cols + holiday_cols + weather_cols + economic_cols + marketing_cols

    if testability["n_entities_with_any_stockout"] < MIN_ENTITIES_WITH_VARIATION:
        # PanelOLS(entity_effects=True) estimates a feature's coefficient
        # from within-entity variation only. With variation in only a
        # handful of the ~6,054 entities, any fitted coefficient would be
        # driven by those few series, not a credible population-level
        # estimate -- forcing a fit here would misrepresent a data-sparsity
        # dead end as a validly-tested "not significant" result. No new
        # MLflow run is logged for this task: there is no viable feature to
        # test, so there is nothing to log as tested. See
        # `07_internal_inventory_report.md` for the full reasoning.
        print(
            f"NOT TESTABLE: only {testability['n_entities_with_any_stockout']} of "
            f"{testability['n_entities_total']} entities ever show a stockout "
            f"(< {MIN_ENTITIES_WITH_VARIATION} floor) -- skipping the fit and MLflow log for this task."
        )
        with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
            f.write("verdict=not_testable\n")
            f.write(f"n_entities_with_any_stockout={testability['n_entities_with_any_stockout']}\n")
            f.write(f"n_entities_total={testability['n_entities_total']}\n")
            f.write("reason=insufficient within-entity variation for a credible PanelOLS coefficient\n")
    else:
        previous_run = fit_and_evaluate(panel, prior_cols, "baseline+calendar+holidays+weather+economic+marketing")
        inventory_run = fit_and_evaluate(
            panel, prior_cols + inventory_cols, "baseline+calendar+holidays+weather+economic+marketing+inventory"
        )

        print(f"Holdout year: {inventory_run['holdout_year']}")
        print("previous metrics:", previous_run["metrics"])
        print("+inventory metrics:", inventory_run["metrics"])

        prev_mape = previous_run["metrics"]["mape"]
        new_mape = inventory_run["metrics"]["mape"]
        mape_improvement = (prev_mape - new_mape) / prev_mape
        meets_threshold = mape_improvement > MAPE_IMPROVEMENT_THRESHOLD
        print(
            f"MAPE improvement vs. previous formula: {mape_improvement:.2%} "
            f"(threshold: >{MAPE_IMPROVEMENT_THRESHOLD:.0%})"
        )
        print(f"Meets threshold: {meets_threshold}")

        coef_table = pd.DataFrame(
            {
                "coefficient": inventory_run["result"].params,
                "std_error": inventory_run["result"].std_errors,
                "t_stat": inventory_run["result"].tstats,
                "p_value": inventory_run["result"].pvalues,
            }
        )
        coef_table.to_csv(OUTPUT_DIR / "coefficients.csv")

        metrics_comparison = pd.DataFrame({"previous": previous_run["metrics"], "+inventory": inventory_run["metrics"]})
        metrics_comparison["pct_change"] = (
            metrics_comparison["+inventory"] - metrics_comparison["previous"]
        ) / metrics_comparison["previous"]
        metrics_comparison.to_csv(OUTPUT_DIR / "metrics_comparison.csv")

        with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
            f.write(
                f"mape_improvement={mape_improvement:.4f}\n"
                f"threshold={MAPE_IMPROVEMENT_THRESHOLD}\n"
                f"meets_threshold={meets_threshold}\n"
            )

        mlflow = init_mlflow_experiment()
        log_run(
            mlflow, inventory_run, prior_cols + inventory_cols, "calendar+holidays+weather+economic+marketing+inventory"
        )
