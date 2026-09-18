# %% [markdown]
# # Task 3.2 — Random Forest on the frozen Stage 2 feature set
#
# Fits ONE `RandomForestRegressor` across every `(product_variant_id,
# location_id)` pair -- deliberately, not as an oversight. `04_demand_classification`
# found 96.8% of the catalog Intermittent / 3.2% Lumpy and `05_croston_sba`
# routed the whole catalog to a segment-aware method on the strength of that
# split. This run tests the hypothesis that RF's tree splits on
# `entity_mean_log_qty` combined with `month_*` can implicitly approximate
# that segmentation without an explicit label -- answered per run via the
# post-hoc per-segment RMSE/bias join in `run_walk_forward()`, not just
# asserted. See `notes.md` for the running log and results.
#
# Scored against the Stage 3 protocol (`experiments/_shared/evaluate.py`):
# refit per rolling-origin cutoff, sum weekly predictions into a 91-day
# window total per series, compare against the `seasonal_naive_genuine_91d_v2`
# champion. Frozen feature set only (`10_frozen_feature_set.md`): `month_2`
# .. `month_12` dummies + `trend`, no other inputs.

# %%
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

FORECASTING = Path(__file__).resolve().parents[2]

# Module-name imports by path, not `import _shared` -- the repo has three
# directories named `_shared`; a package-name import would resolve to
# whichever one Python's import cache saw first. Same technique every other
# Stage 2/3 script already uses.
sys.path.insert(0, str(FORECASTING / "experiments" / "_shared"))
from evaluate import compare_to_baseline, evaluate, get_cutoffs  # noqa: E402
from repro import get_library_versions, get_table_version  # noqa: E402

sys.path.insert(0, str(FORECASTING / "10_feature_engineering" / "_shared"))
from panel_regression import MARTS_SCRATCH, init_mlflow_experiment, load_weekly_panel  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

EXPERIMENT_PATH = "/Shared/02_model_comparison"
DEMAND_CLASSIFICATION_CSV = FORECASTING / "04_demand_classification" / "output" / "demand_classification.csv"
BASELINE_PEAK_SEASON_CSV = FORECASTING / "09_baseline_close_out" / "output" / "genuine_baseline_metrics_peak_season.csv"

HORIZON_WEEKS = 13  # 91 days; month_*/trend are known in advance for any future week ->
# a single model.predict() call covers the whole horizon, no recursive multi-step forecasting.
STRADDLE_LAG = pd.Timedelta(days=6)  # see `run_walk_forward` docstring
TRAIN_END = pd.Timestamp("2024-12-31")  # fixed, matches run_genuine_baseline.py's peak-month reference period

MONTH_COLS = [f"month_{m}" for m in range(2, 13)]
RF_FEATURES = MONTH_COLS + ["trend", "entity_mean_log_qty", "product_variant_id_code", "location_id_code"]

# %% [markdown]
# ## 1. Load the weekly panel once; everything below is derived per-cutoff from it.

# %%
panel = load_weekly_panel()  # period (Monday-anchored weekly Timestamp), product_variant_id (str), location_id (str), qty_sold_net (float)
TREND_ORIGIN = panel["period"].min()


def add_calendar_and_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Frozen feature set only (`10_frozen_feature_set.md`): month_2..month_12 dummies
    (Fourier terms are already excluded centrally in that doc, not re-decided here) +
    `trend`, weeks since the whole panel's first period (fixed at TREND_ORIGIN, not
    re-zeroed per cutoff, so the four rolling windows stay comparable)."""
    df = df.copy()
    dummies = pd.get_dummies(df["period"].dt.month, prefix="month")
    for c in MONTH_COLS:
        if c not in dummies:
            dummies[c] = 0
    df = pd.concat([df, dummies[MONTH_COLS]], axis=1)
    df["trend"] = (df["period"] - TREND_ORIGIN) / pd.Timedelta(weeks=1)
    return df


# Peak months: computed ONCE, from data up to the fixed TRAIN_END only -- matching
# run_genuine_baseline.py's actual approach (a single value reused across all 4 cutoffs
# there, not recomputed per rolling window), so this run's peak-season slice stays
# defined the same way as the champion baseline's peak_season CSV.
_train_end_data = panel[panel["period"] <= TRAIN_END - STRADDLE_LAG]
_monthly = _train_end_data.groupby([_train_end_data["period"].dt.year, _train_end_data["period"].dt.month])["qty_sold_net"].sum()
_avg_by_month = _monthly.groupby(level=1).mean()
PEAK_MONTHS = sorted(_avg_by_month[_avg_by_month > _avg_by_month.mean()].index.tolist())
print(f"Peak-season months (from data <= {TRAIN_END.date()}): {PEAK_MONTHS}")

_segments = pd.read_csv(DEMAND_CLASSIFICATION_CSV, usecols=["product_variant_id", "location_id", "category"])
_segments["product_variant_id"] = _segments["product_variant_id"].astype(str)
_segments["location_id"] = _segments["location_id"].astype(str)


# %% [markdown]
# ## 2. Walk-forward loop
#
# Weeks are Monday-anchored (`date_trunc('week', ...)` in `load_weekly_panel`). The
# protocol's 4 cutoffs (2024-12-31, 2025-04-01, 2025-07-01, 2025-09-30) are all
# Tuesdays (91 = 13*7, so the weekday never shifts), so no week's Monday-anchor lines
# up with a cutoff exactly -- the week containing the cutoff straddles it. That week is
# excluded from BOTH sides:
#   - from train, since summing it would silently pull in a few future days (leakage)
#   - from the scored horizon, since summing it would include a few already-known,
#     pre-cutoff days, overstating true out-of-sample accuracy
# `STRADDLE_LAG` = 6 days implements this: train keeps weeks whose Monday-anchor is
# <= cutoff - 6 days (guaranteeing the whole Mon-Sun week is <= cutoff); the horizon
# starts at the first Monday strictly after cutoff (guaranteeing the whole week is
# > cutoff). This costs at most a handful of days at each boundary relative to the
# baseline's exact 91-day daily-grain window -- an accepted, documented approximation
# of weekly-grain bucketing, not a leakage bug.


# %%
def run_walk_forward(rf_params: dict, run_name: str) -> dict:
    main_rows, peak_rows, importances = [], [], []
    final_model = None

    for cutoff in get_cutoffs():
        train = panel[panel["period"] <= cutoff - STRADDLE_LAG].copy()
        pairs = train[["product_variant_id", "location_id"]].drop_duplicates()

        # Entity identity -- RF's analogue to PanelOLS(entity_effects=True): the entity's
        # own mean level as a numeric feature (fit on training data only, refit per cutoff,
        # no leakage), plus integer codes so RF can find entity x season interactions a
        # fixed-effect intercept can't. Codes are fit on train's categories and REUSED
        # (not refit) for the future frame, so the mapping stays consistent.
        entity_mean = (
            train.assign(log_qty=np.log1p(train["qty_sold_net"]))
            .groupby(["product_variant_id", "location_id"])["log_qty"]
            .mean()
            .rename("entity_mean_log_qty")
            .reset_index()
        )
        train = train.merge(entity_mean, on=["product_variant_id", "location_id"])
        train["product_variant_id_code"] = train["product_variant_id"].astype("category").cat.codes
        train["location_id_code"] = train["location_id"].astype("category").cat.codes
        train = add_calendar_and_trend(train)

        model = RandomForestRegressor(**rf_params, random_state=42, n_jobs=-1)
        model.fit(train[RF_FEATURES], np.log1p(train["qty_sold_net"]))
        final_model = model  # last cutoff's fit -- the one MLflow logs as the run's model artifact

        horizon_periods = pd.date_range(cutoff + pd.Timedelta(days=1), periods=HORIZON_WEEKS, freq="W-MON")

        future = pairs.merge(pd.DataFrame({"period": horizon_periods}), how="cross")
        future = future.merge(entity_mean, on=["product_variant_id", "location_id"], how="left")
        pv_code_map = dict(zip(train["product_variant_id"], train["product_variant_id_code"]))
        loc_code_map = dict(zip(train["location_id"], train["location_id_code"]))
        future["product_variant_id_code"] = future["product_variant_id"].map(pv_code_map)
        future["location_id_code"] = future["location_id"].map(loc_code_map)
        future = add_calendar_and_trend(future)
        # model.predict() returns an ndarray, not a Series -- ndarray.clip() takes
        # min=/max=, not pandas' lower=/upper=.
        future["qty_pred"] = np.expm1(model.predict(future[RF_FEATURES])).clip(min=0)

        # `actual` isn't restricted to `pairs` -- a genuinely new entity that only shows up
        # after the cutoff has no row in `future` (not in `pairs`), so its qty_pred is NaN
        # after the merge below; `.sum(skipna=True)` (pandas default) then reduces an
        # all-NaN entity-window to a predicted total of 0 -- a legitimate "no training
        # history -> forecast 0", not a bug, same as run_genuine_baseline.py's COALESCE(0).
        actual = panel[panel["period"].isin(horizon_periods)]
        weekly = actual.merge(
            future[["product_variant_id", "location_id", "period", "qty_pred"]],
            on=["product_variant_id", "location_id", "period"],
            how="left",
        )
        weekly["is_peak"] = weekly["period"].dt.month.isin(PEAK_MONTHS)

        def _window_totals(g: pd.DataFrame) -> pd.DataFrame:
            out = g.groupby(["product_variant_id", "location_id"], as_index=False).agg(
                actual=("qty_sold_net", "sum"), pred=("qty_pred", "sum")
            )
            out["cutoff"] = cutoff
            return out

        main_rows.append(_window_totals(weekly))
        peak_rows.append(_window_totals(weekly[weekly["is_peak"]]))
        importances.append(pd.Series(model.feature_importances_, index=RF_FEATURES, name=cutoff))

    window_totals = pd.concat(main_rows, ignore_index=True)
    peak_window_totals = pd.concat(peak_rows, ignore_index=True)
    results = evaluate(window_totals)
    peak_results = evaluate(peak_window_totals)
    importance_df = pd.concat(importances, axis=1)  # feature x cutoff
    importance_df["mean_importance"] = importance_df.mean(axis=1)

    # Post-hoc hypothesis diagnostic (NOT a model input -- the frozen feature set stays
    # locked to calendar + trend): does RF's single-model fit close the gap with the
    # explicit Smooth/Intermittent/Lumpy segmentation Strategy 1/2 relied on?
    per_series_by_segment = results["per_series"].merge(_segments, on=["product_variant_id", "location_id"], how="left")
    unmatched = int(per_series_by_segment["category"].isna().sum())
    if unmatched:
        print(f"WARNING: {unmatched}/{len(per_series_by_segment)} series had no demand_classification.csv match")
    segment_summary = per_series_by_segment.groupby("category")[["rmse", "bias"]].mean()

    return {
        "results": results,
        "peak_results": peak_results,
        "importance_df": importance_df,
        "window_totals": window_totals,
        "peak_window_totals": peak_window_totals,
        "segment_summary": segment_summary,
        "final_model": final_model,
    }


# %% [markdown]
# ## 3. MLflow logging
#
# Manual logging only (no `mlflow.sklearn.autolog()`): each run refits 4 models (one per
# cutoff) inside a single `mlflow.start_run()` -- autolog would log a params/model
# artifact per `.fit()` call into that same active run, colliding across folds. The
# explicit `mlflow.sklearn.log_model()` call below (final-cutoff model only) plus the
# manual params/metrics/artifacts cover the tracker's "scikit-learn + MLflow" deliverable
# without that collision.


# %%
def log_run(rf_params: dict, run_name: str, mlflow, data_version: dict, lib_versions: dict) -> None:
    outcome = run_walk_forward(rf_params, run_name)
    results, peak_results = outcome["results"], outcome["peak_results"]

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags(
            {
                "phase": "3_model_comparison",
                "task_ids": "3.2",
                "grain": "weekly (summed to 91d window)",
                "data_source": MARTS_SCRATCH,
                **{f"data_{k}": v for k, v in data_version.items()},
                **lib_versions,
            }
        )
        mlflow.log_params(
            {
                **rf_params,
                "random_state": 42,
                "n_jobs": -1,
                "horizon_weeks": HORIZON_WEEKS,
                "walk_forward_cutoffs": 4,
                "walk_forward_step_days": 91,
                "target_transform": "log1p",
                "entity_encoding": "mean_log_qty+categorical_codes",
            }
        )

        for _, row in results["portfolio"].iterrows():
            cutoff_str = row["cutoff"].date().isoformat()
            mlflow.log_metric(f"wape_pct_{cutoff_str}", row["wape_pct"])
            mlflow.log_metric(f"actual_total_{cutoff_str}", row["actual_total"])
            mlflow.log_metric(f"bias_{cutoff_str}", row["bias"])

        summary = results["per_series_summary"].iloc[0]
        mlflow.log_metrics(
            {
                "rmse_mean": summary["rmse_mean"],
                "rmse_median": summary["rmse_median"],
                "bias_mean": summary["bias_mean"],
            }
        )
        peak_summary = peak_results["per_series_summary"].iloc[0]
        mlflow.log_metrics(
            {
                "peak_rmse_mean": peak_summary["rmse_mean"],
                "peak_rmse_median": peak_summary["rmse_median"],
                "peak_bias_mean": peak_summary["bias_mean"],
            }
        )

        comparison = compare_to_baseline(results["portfolio"])
        mlflow.log_metric("beats_baseline_pct", 100 * comparison["beats_baseline"].mean())

        # Final-cutoff model only (not all 4 folds) -- the tracker's deliverable is "the
        # model", and logging every fold's model would balloon artifact size for little
        # benefit; per-fold feature importances are already captured in importance_df.
        # This mlflow version defaults sklearn model serialization to "skops", which isn't
        # a project dependency (only scikit-learn/mlflow-skinny/pandas/numpy are). cloudpickle
        # is already present transitively via mlflow itself, so use it explicitly rather than
        # adding a new top-level dependency for this.
        mlflow.sklearn.log_model(outcome["final_model"], name="model", serialization_format="cloudpickle")

        for name, df in (
            ("window_totals", outcome["window_totals"]),
            ("peak_window_totals", outcome["peak_window_totals"]),
            ("feature_importance", outcome["importance_df"].reset_index(names="feature")),
            ("segment_summary", outcome["segment_summary"].reset_index()),
            ("compare_to_baseline", comparison),
        ):
            path = OUTPUT_DIR / f"{run_name}_{name}.csv"
            df.to_csv(path, index=False)
            mlflow.log_artifact(str(path))

        print(f"\n=== {run_name} ===")
        print(comparison.to_string(index=False))
        print("\nPer-segment RMSE/bias (post-hoc hypothesis diagnostic):")
        print(outcome["segment_summary"].to_string())
        print("\nTop features by mean importance:")
        print(outcome["importance_df"]["mean_importance"].sort_values(ascending=False).to_string())


# %% [markdown]
# ## 4. Runs -- default config first, then one hyperparameter category at a time
# (no automated search here; that's task 3.3/XGBoost's job)

# %%
RUNS = {
    "random_forest_baseline": dict(n_estimators=300, max_depth=None, min_samples_leaf=1, max_features=1.0),
    "random_forest_depth10": dict(n_estimators=300, max_depth=10, min_samples_leaf=1, max_features=1.0),
    "random_forest_depth20": dict(n_estimators=300, max_depth=20, min_samples_leaf=1, max_features=1.0),
    "random_forest_leaf20": dict(n_estimators=300, max_depth=None, min_samples_leaf=20, max_features=1.0),
    "random_forest_sqrtfeatures": dict(n_estimators=300, max_depth=None, min_samples_leaf=1, max_features="sqrt"),
}

# %%
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run one or more of the RUNS configs; defaults to all.")
    parser.add_argument("run_names", nargs="*", choices=list(RUNS) or None, help="Subset of RUNS keys to execute.")
    args = parser.parse_args()
    selected = {name: RUNS[name] for name in (args.run_names or RUNS)}

    mlflow = init_mlflow_experiment(EXPERIMENT_PATH)
    data_version = get_table_version(MARTS_SCRATCH)
    lib_versions = get_library_versions(["scikit-learn", "pandas", "numpy", "mlflow"])
    print(f"Data snapshot: {data_version}")
    print(f"Library versions: {lib_versions}")
    print(f"Running: {list(selected)}")

    for run_name, rf_params in selected.items():
        log_run(rf_params, run_name, mlflow, data_version, lib_versions)

    print(f"\n{list(selected)} logged under {EXPERIMENT_PATH}. See notes.md for the running log.")
