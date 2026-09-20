# %% [markdown]
# # Task 2.3 -- Add holiday features
#
# Builds on task 2.2's `baseline+calendar` formula, imported directly from
# `02_calendar/add_calendar_features.py` rather than reimplemented -- this
# chain is explicitly cumulative by design (each task extends exactly the
# prior task's formula), unlike the older `forecasting/03`-`09` stages, which
# were independent one-off analyses that only shared small constants.
#
# Calendar is carried forward as a seasonal *control*, not because it
# independently passed its own accuracy threshold (it didn't -- see
# `02_calendar/02_calendar_report.md`): Brazilian holidays cluster in
# specific months (Carnival in Feb/Mar, Christmas/New Year in Dec/Jan), so
# testing holidays without a month control risks the holiday coefficient
# absorbing general seasonal variance that calendar actually explains
# (omitted-variable bias).
#
# `baseline+calendar` is refit here in-memory purely to compute this task's
# MAPE-improvement delta on the exact same code path -- it is NOT re-logged
# to MLflow (task 2.2 already logged it). Only `baseline+calendar+holidays`
# is logged as a new run under `/Shared/01_feature_iteration`.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))

import holidays
import pandas as pd
from add_calendar_features import add_calendar_features

from _shared.panel_regression import MARTS_SCRATCH, fit_and_evaluate, init_mlflow_experiment, load_weekly_panel

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MAPE_IMPROVEMENT_THRESHOLD = 0.02

# %% [markdown]
# ## 1. Holiday features
#
# Uses both the `public` (statutory) and `optional` (informally but widely
# observed, e.g. Carnival, Corpus Christi) categories from the `holidays`
# package's Brazil calendar -- `public` alone would drop Carnival entirely,
# which is central to this feature's own causal hypothesis
# (`00_feature_backlog.md` row 2). National-level holidays only (no
# state/municipal subdivisions), matching the national-level scope task 2.5's
# economic indicators will also use.
#
# Two features: `has_holiday` (week contains >=1 holiday) and
# `is_long_weekend` (week contains a holiday on Mon/Tue/Thu/Fri -- adjacent
# to the weekend, creating or encouraging a 3+ day break; a holiday on
# Wednesday or the weekend itself doesn't reliably grant extra time off).


# %%
def add_holiday_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    # +2, not +1: an ISO week's Monday can fall in `max_year` while the week
    # itself runs into January of `max_year + 1` (e.g. the week of Dec 29
    # 2025 contains Jan 1 2026) -- fetching holidays only through `max_year`
    # would miss that New Year's Day and make `has_holiday` depend on where
    # the caller's panel is truncated.
    years = range(int(df["period"].dt.year.min()), int(df["period"].dt.year.max()) + 2)
    br_holidays = holidays.Brazil(years=years, categories=("public", "optional"))

    holiday_dates = pd.to_datetime(list(br_holidays.keys()))
    holiday_df = pd.DataFrame({"holiday_date": holiday_dates})
    holiday_df["week_start"] = holiday_df["holiday_date"] - pd.to_timedelta(
        holiday_df["holiday_date"].dt.weekday, unit="D"
    )
    holiday_df["is_long_weekend_day"] = holiday_df["holiday_date"].dt.weekday.isin([0, 1, 3, 4])

    weekly_holiday = (
        holiday_df.groupby("week_start")
        .agg(is_long_weekend=("is_long_weekend_day", "any"))
        .reset_index()
    )
    weekly_holiday["has_holiday"] = 1.0
    weekly_holiday["is_long_weekend"] = weekly_holiday["is_long_weekend"].astype(float)

    df = df.merge(
        weekly_holiday[["week_start", "has_holiday", "is_long_weekend"]],
        left_on="period",
        right_on="week_start",
        how="left",
    ).drop(columns=["week_start"])
    df["has_holiday"] = df["has_holiday"].fillna(0.0)
    df["is_long_weekend"] = df["is_long_weekend"].fillna(0.0)

    return df, ["has_holiday", "is_long_weekend"]


# %% [markdown]
# ## 2. MLflow logging (new run only -- `baseline+calendar` was already
# logged by task 2.2)


# %%
def log_run(mlflow, run: dict, feature_cols: list[str], cumulative_features: str):
    with mlflow.start_run(run_name=run["run_name"]) as mlflow_run:
        mlflow.set_tags(
            {
                "phase": "2_feature_engineering",
                "task_ids": "2.3",
                "grain": "product_variant_id x location_id (SKU x Store) x ISO week",
                "source": "forecasting/10_feature_engineering/03_holidays",
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
            }
        )
        for metric, value in run["metrics"].items():
            if isinstance(value, (int, float)) and not pd.isna(value):
                mlflow.log_metric(metric, float(value))
        print(f"Logged run '{run['run_name']}' -> run_id={mlflow_run.info.run_id}")


# %% [markdown]
# ## 3. Fit `baseline+calendar` (previous run, not re-logged) and
# `baseline+calendar+holidays`, compare against the >2% MAPE threshold

# %%
if __name__ == "__main__":
    cache_path = OUTPUT_DIR / "_weekly_panel.parquet"
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        panel = load_weekly_panel()
        panel.to_parquet(cache_path)

    panel, calendar_cols = add_calendar_features(panel)
    panel, holiday_cols = add_holiday_features(panel)

    previous_run = fit_and_evaluate(panel, calendar_cols, "baseline+calendar")
    holiday_run = fit_and_evaluate(panel, calendar_cols + holiday_cols, "baseline+calendar+holidays")

    print(f"Holdout year: {holiday_run['holdout_year']}")
    print("baseline+calendar metrics (previous run):", previous_run["metrics"])
    print("baseline+calendar+holidays metrics:", holiday_run["metrics"])

    prev_mape = previous_run["metrics"]["mape"]
    new_mape = holiday_run["metrics"]["mape"]
    mape_improvement = (prev_mape - new_mape) / prev_mape
    meets_threshold = mape_improvement > MAPE_IMPROVEMENT_THRESHOLD
    print(f"MAPE improvement vs. baseline+calendar: {mape_improvement:.1%} (threshold: >{MAPE_IMPROVEMENT_THRESHOLD:.0%})")
    print(f"Meets threshold: {meets_threshold}")

    coef_table = pd.DataFrame(
        {
            "coefficient": holiday_run["result"].params,
            "std_error": holiday_run["result"].std_errors,
            "t_stat": holiday_run["result"].tstats,
            "p_value": holiday_run["result"].pvalues,
        }
    )
    coef_table.to_csv(OUTPUT_DIR / "coefficients.csv")

    metrics_comparison = pd.DataFrame(
        {"baseline+calendar": previous_run["metrics"], "baseline+calendar+holidays": holiday_run["metrics"]}
    )
    metrics_comparison["pct_change"] = (
        metrics_comparison["baseline+calendar+holidays"] - metrics_comparison["baseline+calendar"]
    ) / metrics_comparison["baseline+calendar"]
    metrics_comparison.to_csv(OUTPUT_DIR / "metrics_comparison.csv")

    with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
        f.write(
            f"mape_improvement={mape_improvement:.4f}\n"
            f"threshold={MAPE_IMPROVEMENT_THRESHOLD}\n"
            f"meets_threshold={meets_threshold}\n"
        )

    mlflow = init_mlflow_experiment()
    log_run(mlflow, holiday_run, calendar_cols + holiday_cols, "calendar+holidays")
