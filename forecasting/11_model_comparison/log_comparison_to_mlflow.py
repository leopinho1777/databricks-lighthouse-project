# %%
"""Log the final Stage 3 comparison (task 3.7) as one consolidated MLflow run.

Reads the CSVs `build_comparison.py` wrote (run that first) and logs them to the shared Stage 3 experiment
next to the individual model runs, so one screen holds both the per-model runs and the side-by-side result.
Only the main-table models get per-metric entries; every configuration is in the logged CSV artifacts.
"""

import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
FORECASTING = HERE.parent
EXPERIMENT_PATH = "/Shared/02_model_comparison"
RUN_NAME = "final_comparison_3_7"

sys.path.insert(0, str(FORECASTING / "10_feature_engineering" / "_shared"))
sys.path.insert(0, str(FORECASTING / "experiments" / "_shared"))
from panel_regression import init_mlflow_experiment  # noqa: E402
from repro import get_library_versions  # noqa: E402

REPORT = HERE / "11_model_comparison_report.md"


# %%
def slug(name: str) -> str:
    """MLflow-safe metric prefix: lowercase, non-alphanumerics collapsed to underscores."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    summary = pd.read_csv(OUTPUT_DIR / "comparison_summary.csv")
    sku = pd.read_csv(OUTPUT_DIR / "comparison_sku_portfolio.csv", parse_dates=["cutoff"])
    main_models = summary[summary["in_main_table"]]

    mlflow = init_mlflow_experiment(EXPERIMENT_PATH)
    with mlflow.start_run(run_name=RUN_NAME):
        mlflow.set_tags(
            {
                "phase": "3_model_comparison",
                "task_ids": "3.7",
                "source": "committed *_window_totals.csv of each experiment; no model refit",
                # Each source run used its own data snapshot (delta versions 4-6), so no single table version applies.
                "data_snapshot": "per source run, see each experiment's README.md",
                "baseline": "seasonal_naive_genuine_91d_v2 (committed portfolio CSV, not recomputed)",
                "peak_windows": "2024-12-31, 2025-09-30",
                **get_library_versions(["pandas", "numpy", "mlflow"]),
            }
        )
        mlflow.log_params(
            {
                "n_configurations": len(summary) - 1,
                "n_main_table_models": len(main_models),
                "windows": "2024-12-31, 2025-04-01, 2025-07-01, 2025-09-30",
                "horizon_days": 91,
            }
        )

        for _, row in main_models.iterrows():
            prefix = slug(row["model"])
            per_window = sku[sku["model"] == row["model"]]
            for _, w in per_window.iterrows():
                mlflow.log_metric(f"{prefix}__wape_pct_{w['cutoff'].date().isoformat()}", float(w["wape_pct"]))
            scalars = {
                "wape_mean": row["wape_mean"], "wape_peak": row["wape_peak"], "wape_offpeak": row["wape_offpeak"],
                "bias_pct_mean": row["bias_pct_mean"], "rmse_mean": row["rmse_mean"], "rmse_median": row["rmse_median"],
                "bias_mean_per_series": row["bias_mean_per_series"], "cat_wape_mean": row["cat_wape_mean"],
                "windows_beating_baseline": row["windows_beating_baseline"],
            }
            # Champion has no comparable per-series/category metrics: skip NaNs instead of logging them.
            mlflow.log_metrics({f"{prefix}__{k}": float(v) for k, v in scalars.items() if pd.notna(v)})

        mlflow.log_artifacts(str(OUTPUT_DIR))
        mlflow.log_artifact(str(REPORT))
        print(f"Logged run {RUN_NAME!r} to {EXPERIMENT_PATH}")


# %%
if __name__ == "__main__":
    main()
