# %% [markdown]
# # Task 1.8 — Log the corrected baseline as 'Experiment 0' in MLflow
#
# No MLflow usage existed anywhere in this repo before this stage (checked via
# repo-wide grep). Logs the genuine 91-day, held-static baseline numbers from
# `run_genuine_baseline.py` -- not `03`'s or `08`'s numbers, since those
# understate the real 3-month-ahead error (see
# `09_baseline_close_out_summary.md`).

# %%
import os
import sys
from pathlib import Path

import mlflow
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared.db_connection import PROD_MARTS, _load_dev_profile  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
EXPERIMENT_PATH = "/Shared/00_baseline"

# %% [markdown]
# ## 1. Point MLflow at the workspace using the existing dbt dev profile
#
# Same credential source `_shared/db_connection.py` already uses for the SQL
# warehouse connection -- no new secrets.

# %%
profile = _load_dev_profile()
os.environ.setdefault("DATABRICKS_HOST", f"https://{profile['host']}")
if profile.get("token"):
    os.environ.setdefault("DATABRICKS_TOKEN", profile["token"])

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(EXPERIMENT_PATH)

# %% [markdown]
# ## 2. Log the corrected Moving Average and Seasonal Naive runs

# %%
overall = pd.read_csv(OUTPUT_DIR / "genuine_baseline_metrics_overall.csv").set_index("baseline")
peak = pd.read_csv(OUTPUT_DIR / "genuine_baseline_metrics_peak_season.csv").set_index("baseline")
portfolio = pd.read_csv(OUTPUT_DIR / "genuine_baseline_metrics_portfolio.csv")

logged_run_ids = {}
for name in overall.index:
    with mlflow.start_run(run_name=f"{name}_genuine_91d_v2") as run:
        mlflow.set_tags(
            {
                "phase": "1_baseline_model_definition",
                "task_ids": "1.3" if name == "seasonal_naive" else "1.4",
                "grain": "product_variant_id x location_id (SKU x Store)",
                "source": "forecasting/09_baseline_close_out (fixes 03/08's continuously-refreshed horizon bug)",
                "data_source": f"{PROD_MARTS}.fct_sales",
            }
        )
        mlflow.log_params(
            {
                "baseline": name,
                "horizon_days": 91,
                "walk_forward_cutoffs": 4,
                "walk_forward_step_days": 91,
                "validate_year": 2025,
                "train_end": "2024-12-31",
                "forecast_held_static": True,
            }
        )
        for metric in ("rmse", "bias", "mape", "smape"):
            mlflow.log_metric(metric, float(overall.loc[name, metric]))
            mlflow.log_metric(f"peak_season_{metric}", float(peak.loc[name, metric]))
        wape_mean = portfolio.loc[portfolio["baseline"] == name, "wape_pct"].mean()
        mlflow.log_metric("portfolio_wape_pct_mean", float(wape_mean))
        logged_run_ids[name] = run.info.run_id
        print(f"Logged run '{name}_genuine_91d_v2' -> run_id={run.info.run_id}")

# %% [markdown]
# ## 3. Confirm both runs are visible in the experiment

# %%
experiment = mlflow.get_experiment_by_name(EXPERIMENT_PATH)
runs = mlflow.search_runs(experiment_ids=[experiment.experiment_id])
print(runs[["run_id", "tags.mlflow.runName", "metrics.rmse", "metrics.portfolio_wape_pct_mean"]].to_string(index=False))

# %%
if __name__ == "__main__":
    print(f"\nExperiment: {EXPERIMENT_PATH} (id={experiment.experiment_id})")
    print(f"Run IDs: {logged_run_ids}")
