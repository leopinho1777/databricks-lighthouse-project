# %% [markdown]
# # Task 2.2 -- Add calendar & seasonality features
#
# First cumulative feature addition on top of the (feature-less) entity-fixed-
# effects panel regression. Calendar/seasonality is the lowest-risk,
# highest-certainty feature group given how seasonal boating demand is
# (Southern-hemisphere summer, Nov-Feb) -- see `00_feature_backlog.md` row 1.
#
# Fits and logs TWO MLflow runs under `/Shared/01_feature_iteration`:
# `entity_fe_only` (the zero-feature reference every cumulative task's
# MAPE-improvement delta is measured against) and `baseline+calendar`. The
# keep/drop verdict is decided by the delta between them against the
# tracker's >2% MAPE-improvement threshold, not by coefficient significance
# alone -- significance answers "is the effect real", the delta answers
# "does it improve forecast accuracy enough to keep".

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from _shared.panel_regression import fit_and_evaluate, init_mlflow_experiment, load_weekly_panel

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MAPE_IMPROVEMENT_THRESHOLD = 0.02

# %% [markdown]
# ## 1. Load the weekly panel and derive calendar features from `period`
#
# Regression grain is weekly, so day-of-week/is_weekend (daily concepts) don't
# apply per row -- every week contains the same 5 weekdays + 2 weekend days
# regardless of season. Quarter is dropped: as a dummy set it would be a
# perfect linear combination of the month dummies below (each quarter maps to
# exactly 3 specific months), which would make the design matrix singular.
# Month dummies capture the Southern-summer/winter split the causal hypothesis
# cares about; week-of-year is added as a continuous sin/cos pair for finer
# within-month seasonality without adding 52 more dummy columns.


# %%
def add_calendar_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df["month"] = df["period"].dt.month
    week_of_year = df["period"].dt.isocalendar().week.astype(int)
    df["week_of_year_sin"] = np.sin(2 * np.pi * week_of_year / 52)
    df["week_of_year_cos"] = np.cos(2 * np.pi * week_of_year / 52)

    month_dummies = pd.get_dummies(df["month"], prefix="month", drop_first=True, dtype=float)
    df = pd.concat([df, month_dummies], axis=1)

    feature_cols = list(month_dummies.columns) + ["week_of_year_sin", "week_of_year_cos"]
    return df, feature_cols


# %% [markdown]
# ## 2. Shared MLflow logging for both runs


# %%
def log_run(mlflow, run: dict, feature_cols: list[str], cumulative_features: str):
    with mlflow.start_run(run_name=run["run_name"]) as mlflow_run:
        mlflow.set_tags(
            {
                "phase": "2_feature_engineering",
                "task_ids": "2.2",
                "grain": "product_variant_id x location_id (SKU x Store) x ISO week",
                "source": "forecasting/10_feature_engineering/02_calendar",
                "data_source": "develop.eros_analytics_forecasting_scratch.fact_demand_daily",
                "formula": "+".join(["entity_fe"] + feature_cols) if feature_cols else "entity_fe",
            }
        )
        mlflow.log_params(
            {
                "cumulative_features": cumulative_features,
                "holdout_year": run["holdout_year"],
                "n_feature_cols": len(feature_cols),
                "estimator": "PanelOLS(entity_effects=True)" if feature_cols else "entity_mean_only",
                "target": "log1p(qty_sold_net)",
            }
        )
        for metric, value in run["metrics"].items():
            if isinstance(value, (int, float)) and not pd.isna(value):
                mlflow.log_metric(metric, float(value))
        print(f"Logged run '{run['run_name']}' -> run_id={mlflow_run.info.run_id}")


# %% [markdown]
# ## 3. Fit the zero-feature reference, fit the calendar run, compare

# %%
if __name__ == "__main__":
    cache_path = OUTPUT_DIR / "_weekly_panel.parquet"
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        panel = load_weekly_panel()
        panel.to_parquet(cache_path)

    panel, feature_cols = add_calendar_features(panel)

    reference_run = fit_and_evaluate(panel, [], "entity_fe_only")
    calendar_run = fit_and_evaluate(panel, feature_cols, "baseline+calendar")

    print(f"Holdout year: {calendar_run['holdout_year']}")
    print("entity_fe_only metrics:", reference_run["metrics"])
    print("baseline+calendar metrics:", calendar_run["metrics"])

    ref_mape = reference_run["metrics"]["mape"]
    cal_mape = calendar_run["metrics"]["mape"]
    mape_improvement = (ref_mape - cal_mape) / ref_mape
    meets_threshold = mape_improvement > MAPE_IMPROVEMENT_THRESHOLD
    print(f"MAPE improvement vs. entity_fe_only: {mape_improvement:.1%} (threshold: >{MAPE_IMPROVEMENT_THRESHOLD:.0%})")
    print(f"Meets threshold: {meets_threshold}")

    coef_table = pd.DataFrame(
        {
            "coefficient": calendar_run["result"].params,
            "std_error": calendar_run["result"].std_errors,
            "t_stat": calendar_run["result"].tstats,
            "p_value": calendar_run["result"].pvalues,
        }
    )
    coef_table.to_csv(OUTPUT_DIR / "coefficients.csv")

    metrics_comparison = pd.DataFrame(
        {"entity_fe_only": reference_run["metrics"], "baseline+calendar": calendar_run["metrics"]}
    )
    metrics_comparison["pct_change"] = (
        metrics_comparison["baseline+calendar"] - metrics_comparison["entity_fe_only"]
    ) / metrics_comparison["entity_fe_only"]
    metrics_comparison.to_csv(OUTPUT_DIR / "metrics_comparison.csv")

    with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
        f.write(
            f"mape_improvement={mape_improvement:.4f}\n"
            f"threshold={MAPE_IMPROVEMENT_THRESHOLD}\n"
            f"meets_threshold={meets_threshold}\n"
        )

    # %% [markdown]
    # ## 4. Log both runs to MLflow (`/Shared/01_feature_iteration`, same
    # pattern as `09_baseline_close_out/log_baseline_to_mlflow.py`)

    # %%
    mlflow = init_mlflow_experiment()
    log_run(mlflow, reference_run, [], "none (entity fixed effects only)")
    log_run(mlflow, calendar_run, feature_cols, "calendar")
