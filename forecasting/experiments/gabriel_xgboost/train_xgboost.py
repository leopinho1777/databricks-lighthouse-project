# %% [markdown]
# # Task 3.3 — XGBoost on the frozen Stage 2 feature set (+ daily-grain lags)
#
# Trains a single global XGBoost model (all ~6,054 product x location series
# together, not one model per series) to predict the total quantity sold over
# a 91-day horizon -- the same aggregate `seasonal_naive_genuine_91d_v2`
# (the champion in `/Shared/00_baseline`) is scored on.
#
# Why a single global model and not one per series: `period_sufficiency_check.csv`
# (`07_hierarchical_reconciliation/stage4_mint_feasibility`) already showed
# each of the ~6,054 product x location series has only ~1 year of usable daily
# history -- nowhere near enough to fit a separate model per series. Pooling
# all series into one model (product/location become feature columns, not
# separate models) is the only approach the data actually supports.
#
# Why the target is a single 91-day total, not 91 daily predictions: this is
# the same aggregate the champion is scored on, so WAPE is directly comparable.
# It also sidesteps the recursive-forecast problem entirely (a day-by-day
# model would need to feed its own predictions back in as lags to reach day
# 91, compounding error the whole way) -- predicting the 91-day total in one
# shot is the most direct approach. Fitting at daily grain (not weekly, unlike
# `eros_randomforest`) is a free choice under the protocol ("fit at whatever
# grain suits your model") -- daily keeps the lag/rolling features below at
# their native resolution instead of losing information to a weekly rollup.
#
# Frozen feature set (`10_feature_engineering/10_frozen_feature_set.md`):
# calendar survives as the only tested exogenous feature, and `trend` is a
# mandatory structural control for every Stage 3 model ("XGBoost/Random
# Forest need it as an explicit engineered feature the same way this stage
# did -- they have no native trend concept"). Both are included below
# (`month` categorical + explicit `trend` = days since `DENSE_START`).
# Holiday/weather/economic/marketing are NOT re-added -- already tested and
# rejected centrally, not re-decided here. Everything else in `FEATURE_COLS`
# (trailing sums, same-period-last-year, rolling std, demand_category) is
# this model's own addition, same latitude `eros_randomforest` used for its
# entity encoding -- the protocol only mandates shared *scoring*, not a
# shared feature list.
#
# Hyperparameters are NOT hand-picked. They're found with Hyperopt on a
# validation fold that is strictly earlier than the 4 official protocol
# cutoffs, so the official numbers are never used to choose the model -- see
# `TUNE_CUTOFF` vs `TEST_CUTOFFS`.
#
# Scored against the Stage 3 protocol (`experiments/_shared/evaluate.py`):
# refit per rolling-origin cutoff, one-shot 91-day-total prediction per
# series, compare against the `seasonal_naive_genuine_91d_v2` champion.
# MAPE/sMAPE are excluded from all reporting, per `05_croston_sba`'s finding
# that they're structurally uninformative on this catalog.

# %%
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from hyperopt import STATUS_OK, Trials, fmin, hp, tpe

FORECASTING = Path(__file__).resolve().parents[2]

# Module-name imports by path, not `import _shared` -- the repo has three
# directories named `_shared`; a package-name import would resolve to
# whichever one Python's import cache saw first. Same technique every other
# Stage 2/3 script already uses.
sys.path.insert(0, str(FORECASTING / "experiments" / "_shared"))
from evaluate import compare_to_baseline, evaluate, get_cutoffs  # noqa: E402
from repro import get_library_versions, get_table_version  # noqa: E402

sys.path.insert(0, str(FORECASTING / "10_feature_engineering" / "_shared"))
from panel_regression import init_mlflow_experiment  # noqa: E402

_DB_CONNECTION_PATH = FORECASTING / "_shared" / "db_connection.py"
_spec = importlib.util.spec_from_file_location("forecasting_shared_db_connection_xgb", _DB_CONNECTION_PATH)
_db_connection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_connection)
query_df = _db_connection.query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MARTS = "develop.eva_analytics_marts"  # same source as 08/09, see forecasting/README.md's data-source convention
KEYS = ["product_variant_id", "location_id"]
HORIZON_DAYS = 91
EXPERIMENT_PATH = "/Shared/02_model_comparison"

DEMAND_CLASSIFICATION_CSV = FORECASTING / "04_demand_classification" / "output" / "demand_classification.csv"

# --- Date plan -----------------------------------------------------------
# Protocol cutoffs, imported rather than re-derived, so they never drift from
# the baseline's (`experiments/_shared/evaluate.py`'s docstring).
TEST_CUTOFFS = get_cutoffs()
FIRST_OFFICIAL_CUTOFF = TEST_CUTOFFS[0]  # 2024-12-31
VALIDATE_END = TEST_CUTOFFS[-1] + pd.Timedelta(days=HORIZON_DAYS)  # 2025-12-31, last window's end

# Dense panel start: as early as fct_sales goes (01_data_exploration_summary.md:
# 2020-01-01), so the "same period last year" feature has real history behind it,
# and the trend feature has a stable, shared origin.
DENSE_START = pd.Timestamp("2020-01-01")
# First training origin needs >= 456 days of history before it (91d for the
# longest trailing window + 365d to look back a further year for the
# same-period-last-year feature).
TRAIN_ORIGIN_START = pd.Timestamp("2021-04-01")
# Held-out fold used ONLY to pick hyperparameters. Its target window
# (TUNE_CUTOFF+1 .. TUNE_CUTOFF+91) ends 2024-09-29 -- strictly before the
# first official cutoff, so tuning never sees official-window data.
TUNE_CUTOFF = pd.Timestamp("2024-06-30")
# Training origins for the hyperparameter search must not overlap the tuning
# validation window: last such origin + 91d must be <= TUNE_CUTOFF.
HYPEROPT_TRAIN_END = TUNE_CUTOFF - pd.Timedelta(days=HORIZON_DAYS)
# After hyperparameters are locked, refit on all pre-test history (including
# the period used for tuning) -- standard practice once model selection is
# done. Its last origin's target window must still end before the first
# official cutoff.
FINAL_FIT_END = FIRST_OFFICIAL_CUTOFF - pd.Timedelta(days=HORIZON_DAYS)
ORIGIN_STEP_DAYS = 30  # overlapping origins on purpose: unlike the baseline (a running average),
# XGBoost needs many training rows per series, not just 4 non-overlapping folds.

SALES = f"""
vendas AS (
    SELECT s.product_variant_id, s.location_id, DATE(s.placed_at) AS dia, s.quantity
    FROM {MARTS}.fct_sales AS s
    WHERE s.order_status IN ('paid', 'confirmed')
)"""

# %% [markdown]
# ## 1. Dense daily panel (product x location x day), zero-filled
#
# Same pairs/dense-grid SQL pattern `09_baseline_close_out` uses for its
# moving-average query, but pulled once into pandas -- feature engineering
# below needs the full daily series per pair, not just one window's average.


# %%
def load_dense_panel() -> pd.DataFrame:
    """Returns a dense (date x (product, location)) wide matrix, zero-filled.

    Pulls only the SPARSE actual (pair, day)-with-sales rows from SQL -- not
    a CROSS JOIN of all pairs x all days, which would transmit ~13M mostly-
    zero rows over the wire and OOM-kill the process locally. The zero-fill
    (via `reindex`) happens here in pandas/numpy instead, which is orders of
    magnitude cheaper than deserializing that many rows through the
    connector.
    """
    sql = f"""
    WITH {SALES}
    SELECT {", ".join(KEYS)}, dia, SUM(quantity) AS qty
    FROM vendas
    WHERE dia BETWEEN DATE'{DENSE_START.date()}' AND DATE'{VALIDATE_END.date()}'
    GROUP BY {", ".join(KEYS)}, dia
    """
    sparse = query_df(sql)
    sparse["dia"] = pd.to_datetime(sparse["dia"])
    sparse["qty"] = sparse["qty"].astype("float32")
    for key in KEYS:
        sparse[key] = sparse[key].astype("int64")  # connector returns these as object/Decimal

    pairs_sql = f"WITH {SALES} SELECT DISTINCT {', '.join(KEYS)} FROM vendas"
    all_pairs = query_df(pairs_sql)
    for key in KEYS:
        all_pairs[key] = all_pairs[key].astype("int64")

    wide = sparse.pivot(index="dia", columns=KEYS, values="qty")
    wide = wide.reindex(pd.date_range(DENSE_START, VALIDATE_END, freq="D"))
    wide.index.name = "dia"  # reindex() drops the name -- build_examples' melt() merges on it
    wide = wide.reindex(columns=pd.MultiIndex.from_frame(all_pairs))
    return wide.fillna(0.0).astype("float32")


# %% [markdown]
# ## 2. Peak season months, derived the same way `09_baseline_close_out` does
#
# Average monthly total over the train years only (no validation-year leakage).


# %%
def compute_peak_months() -> list:
    monthly_totals = query_df(f"""
        WITH {SALES}
        SELECT MONTH(dia) AS month, YEAR(dia) AS year, SUM(quantity) AS total_qty
        FROM vendas WHERE dia <= DATE'{FIRST_OFFICIAL_CUTOFF.date()}'
        GROUP BY MONTH(dia), YEAR(dia)
    """)
    avg_by_month = monthly_totals.groupby("month")["total_qty"].mean()
    return sorted(avg_by_month[avg_by_month > avg_by_month.mean()].index.tolist())


# %% [markdown]
# ## 3. Feature/target table -- one row per (series, origin)
#
# Every feature uses only data <= origin; the target is the 91-day total
# strictly *after* origin (origin+1 .. origin+91) -- the same aggregate the
# baseline is scored on. Vectorized with cumulative sums across the whole
# wide panel at once instead of looping per series (~6,054 series x ~50
# origins would be far too slow row-by-row).


# %%
def build_examples(wide: pd.DataFrame, origins: pd.DatetimeIndex, category_lookup: pd.DataFrame) -> pd.DataFrame:
    """`wide`: dense (date x (product, location)) matrix, as returned by `load_dense_panel()`."""
    cum = wide.cumsum()

    def trailing_sum(n: int) -> pd.DataFrame:
        """Sum of the n days ending at (and including) each row's date."""
        return cum - cum.shift(n).fillna(0.0)

    trailing_7 = trailing_sum(7)
    trailing_28 = trailing_sum(28)
    trailing_91 = trailing_sum(91)
    same_period_last_year = trailing_91.shift(365)  # the 91-day window ending exactly a year earlier
    rolling_std_28 = wide.rolling(28).std()
    nonzero_days_91 = (wide > 0).rolling(91).sum()
    target = cum.shift(-HORIZON_DAYS) - cum  # sum of qty over origin+1 .. origin+HORIZON_DAYS

    def melt(df: pd.DataFrame, name: str) -> pd.DataFrame:
        out = df.loc[df.index.isin(origins)].stack(KEYS, future_stack=True).rename(name).reset_index()
        return out

    features = melt(trailing_7, "trailing_qty_7d")
    for extra_df, name in [
        (trailing_28, "trailing_qty_28d"),
        (trailing_91, "trailing_qty_91d"),
        (same_period_last_year, "same_period_last_year_qty"),
        (rolling_std_28, "rolling_std_28d"),
        (nonzero_days_91, "nonzero_days_trailing_91d"),
        (target, "target_qty_next_91d"),
    ]:
        features = features.merge(melt(extra_df, name), on=["dia"] + KEYS, how="left")

    features["origin"] = features["dia"]
    features["month"] = features["dia"].dt.month
    features["day_of_week"] = features["dia"].dt.dayofweek
    # Frozen-feature-set mandatory structural control (`10_frozen_feature_set.md`
    # section 2): trees have no native trend concept, so it has to be an explicit
    # feature. Days since the panel's shared origin -- fixed at DENSE_START, not
    # re-zeroed per origin, so the four rolling test windows stay comparable.
    features["trend"] = (features["origin"] - DENSE_START).dt.days
    features = features.drop(columns=["dia"])

    features = features.merge(category_lookup, on=KEYS, how="left")
    features["demand_category"] = features["demand_category"].fillna("insufficient_data").astype("category")
    for key in KEYS:
        features[key] = features[key].astype("category")

    return features


# %% [markdown]
# ## 4. Hyperparameter search (Hyperopt), logged as nested MLflow runs
#
# The validation fold (`TUNE_CUTOFF`) is never touched by training rows used
# in this search -- see `HYPEROPT_TRAIN_END` above. `Trials()` (not
# `SparkTrials()`): these scripts run locally against the SQL warehouse via
# `databricks-sql-connector`, not as a notebook attached to a Spark cluster,
# so distributed trial execution isn't available here.


# %%
FEATURE_COLS = [
    "trailing_qty_7d",
    "trailing_qty_28d",
    "trailing_qty_91d",
    "same_period_last_year_qty",
    "rolling_std_28d",
    "nonzero_days_trailing_91d",
    "month",
    "day_of_week",
    "trend",
    "demand_category",
] + KEYS

SEARCH_SPACE = {
    "max_depth": hp.quniform("max_depth", 3, 10, 1),
    "learning_rate": hp.loguniform("learning_rate", np.log(0.01), np.log(0.3)),
    "n_estimators": hp.quniform("n_estimators", 100, 800, 50),
    "subsample": hp.uniform("subsample", 0.6, 1.0),
    "colsample_bytree": hp.uniform("colsample_bytree", 0.6, 1.0),
    "min_child_weight": hp.quniform("min_child_weight", 1, 10, 1),
    "reg_alpha": hp.loguniform("reg_alpha", np.log(1e-4), np.log(10)),
    "reg_lambda": hp.loguniform("reg_lambda", np.log(1e-4), np.log(10)),
}


def _cast_params(raw: dict) -> dict:
    return {
        "max_depth": int(raw["max_depth"]),
        "learning_rate": float(raw["learning_rate"]),
        "n_estimators": int(raw["n_estimators"]),
        "subsample": float(raw["subsample"]),
        "colsample_bytree": float(raw["colsample_bytree"]),
        "min_child_weight": int(raw["min_child_weight"]),
        "reg_alpha": float(raw["reg_alpha"]),
        "reg_lambda": float(raw["reg_lambda"]),
    }


def fit_xgboost(params: dict, train_df: pd.DataFrame) -> xgb.XGBRegressor:
    model = xgb.XGBRegressor(
        objective="reg:squarederror",
        tree_method="hist",
        enable_categorical=True,
        random_state=42,
        **params,
    )
    model.fit(train_df[FEATURE_COLS], train_df["target_qty_next_91d"])
    return model


def portfolio_wape(actual: pd.Series, pred: pd.Series) -> float:
    return 100 * (actual - pred).abs().sum() / actual.sum()


def run_hyperopt_search(
    hyperopt_train_df: pd.DataFrame, hyperopt_val_df: pd.DataFrame, mlflow, max_evals: int = 30
) -> dict:
    def objective(raw_params):
        params = _cast_params(raw_params)
        with mlflow.start_run(nested=True):
            model = fit_xgboost(params, hyperopt_train_df)
            pred = model.predict(hyperopt_val_df[FEATURE_COLS])
            wape = portfolio_wape(hyperopt_val_df["target_qty_next_91d"], pd.Series(pred, index=hyperopt_val_df.index))
            mlflow.log_params(params)
            mlflow.log_metric("val_wape_pct", wape)
        return {"loss": wape, "status": STATUS_OK}

    trials = Trials()
    with mlflow.start_run(run_name="xgboost_hyperparam_search") as parent_run:
        mlflow.set_tags({"phase": "3_model_comparison", "task_ids": "3.3", "role": "hyperopt_search"})
        best_raw = fmin(fn=objective, space=SEARCH_SPACE, algo=tpe.suggest, max_evals=max_evals, trials=trials)
        best_params = _cast_params(
            {
                "max_depth": best_raw["max_depth"],
                "learning_rate": best_raw["learning_rate"],
                "n_estimators": best_raw["n_estimators"],
                "subsample": best_raw["subsample"],
                "colsample_bytree": best_raw["colsample_bytree"],
                "min_child_weight": best_raw["min_child_weight"],
                "reg_alpha": best_raw["reg_alpha"],
                "reg_lambda": best_raw["reg_lambda"],
            }
        )
        mlflow.log_params({f"best_{k}": v for k, v in best_params.items()})
        print(f"Best params (search parent run_id={parent_run.info.run_id}): {best_params}")
    return best_params


# %% [markdown]
# ## 5. Official walk-forward evaluation -- scored via the shared Stage 3 protocol


# %%
def run_walk_forward_official(model: xgb.XGBRegressor, test_df: pd.DataFrame, peak_months: list) -> dict:
    """Builds `window_totals` in the shape `experiments/_shared/evaluate.py` expects
    (one row per series per cutoff, `actual`/`pred` already summed over the 91-day
    window -- which for this single-shot model is just the raw prediction, no
    further summing needed) and scores through it, same protocol every other
    Stage 3 model uses.
    """
    test_df = test_df.copy()
    test_df["pred"] = model.predict(test_df[FEATURE_COLS])
    test_df["is_peak"] = test_df["month"].isin(peak_months)

    window_totals = test_df.rename(columns={"origin": "cutoff", "target_qty_next_91d": "actual"})[
        KEYS + ["cutoff", "actual", "pred"]
    ]
    peak_window_totals = test_df[test_df["is_peak"]].rename(
        columns={"origin": "cutoff", "target_qty_next_91d": "actual"}
    )[KEYS + ["cutoff", "actual", "pred"]]

    results = evaluate(window_totals)
    peak_results = evaluate(peak_window_totals)

    segments = pd.read_csv(DEMAND_CLASSIFICATION_CSV, usecols=["product_variant_id", "location_id", "category"])
    for key in KEYS:
        segments[key] = segments[key].astype(str)
    per_series = results["per_series"].copy()
    for key in KEYS:
        per_series[key] = per_series[key].astype(str)
    per_series_by_segment = per_series.merge(segments, on=KEYS, how="left")
    unmatched = int(per_series_by_segment["category"].isna().sum())
    if unmatched:
        print(f"WARNING: {unmatched}/{len(per_series_by_segment)} series had no demand_classification.csv match")
    segment_summary = per_series_by_segment.groupby("category")[["rmse", "bias"]].mean()

    return {
        "results": results,
        "peak_results": peak_results,
        "window_totals": window_totals,
        "peak_window_totals": peak_window_totals,
        "segment_summary": segment_summary,
    }


# %% [markdown]
# ## 6. Run everything


# %%
if __name__ == "__main__":
    mlflow = init_mlflow_experiment(EXPERIMENT_PATH)

    data_version = get_table_version(f"{MARTS}.fct_sales")
    lib_versions = get_library_versions(["xgboost", "hyperopt", "pandas", "numpy", "mlflow"])
    print(f"Data snapshot: {data_version}")
    print(f"Library versions: {lib_versions}")

    print("Loading dense daily panel...")
    panel = load_dense_panel()

    category_lookup = pd.read_csv(DEMAND_CLASSIFICATION_CSV)[KEYS + ["category"]].rename(
        columns={"category": "demand_category"}
    )
    for key in KEYS:
        category_lookup[key] = category_lookup[key].astype("int64")

    hyperopt_train_origins = pd.date_range(TRAIN_ORIGIN_START, HYPEROPT_TRAIN_END, freq=f"{ORIGIN_STEP_DAYS}D")
    final_train_origins = pd.date_range(TRAIN_ORIGIN_START, FINAL_FIT_END, freq=f"{ORIGIN_STEP_DAYS}D")
    all_origins = hyperopt_train_origins.union([TUNE_CUTOFF]).union(final_train_origins).union(TEST_CUTOFFS)

    print(f"Building features for {len(all_origins)} origins x {panel.shape[1]:,} series...")
    examples = build_examples(panel, all_origins, category_lookup)
    examples = examples.dropna(subset=FEATURE_COLS + ["target_qty_next_91d"])

    hyperopt_train_df = examples[examples["origin"].isin(hyperopt_train_origins)]
    hyperopt_val_df = examples[examples["origin"] == TUNE_CUTOFF]
    final_train_df = examples[examples["origin"].isin(final_train_origins)]
    test_df = examples[examples["origin"].isin(TEST_CUTOFFS)]

    print(
        f"hyperopt_train={len(hyperopt_train_df):,} hyperopt_val={len(hyperopt_val_df):,} "
        f"final_train={len(final_train_df):,} test={len(test_df):,}"
    )

    print(f"Running Hyperopt search (validation fold: {TUNE_CUTOFF.date()})...")
    best_params = run_hyperopt_search(hyperopt_train_df, hyperopt_val_df, mlflow, max_evals=30)

    print("Refitting final model on all pre-test history with locked params...")
    final_model = fit_xgboost(best_params, final_train_df)

    peak_months = compute_peak_months()
    print(f"Peak-season months: {peak_months}")

    print(f"Scoring the {len(TEST_CUTOFFS)} official protocol cutoffs: {[c.date() for c in TEST_CUTOFFS]}")
    outcome = run_walk_forward_official(final_model, test_df, peak_months)
    results, peak_results = outcome["results"], outcome["peak_results"]
    comparison = compare_to_baseline(results["portfolio"])

    with mlflow.start_run(run_name="xgboost_v1"):
        mlflow.set_tags(
            {
                "phase": "3_model_comparison",
                "task_ids": "3.3",
                "grain": "daily (single-shot 91d target, no recursive forecasting)",
                "data_source": f"{MARTS}.fct_sales",
                "model_scope": "single_global_model",
                "hyperparameter_search": "hyperopt (see xgboost_hyperparam_search parent run)",
                **{f"data_{k}": v for k, v in data_version.items()},
                **lib_versions,
            }
        )
        mlflow.log_params(
            {
                **{f"xgb_{k}": v for k, v in best_params.items()},
                "horizon_days": HORIZON_DAYS,
                "walk_forward_cutoffs": len(TEST_CUTOFFS),
                "target_transform": "none",
            }
        )

        for _, row in results["portfolio"].iterrows():
            cutoff_str = row["cutoff"].date().isoformat()
            mlflow.log_metric(f"wape_pct_{cutoff_str}", row["wape_pct"])
            mlflow.log_metric(f"actual_total_{cutoff_str}", row["actual_total"])
            mlflow.log_metric(f"bias_{cutoff_str}", row["bias"])

        summary = results["per_series_summary"].iloc[0]
        mlflow.log_metrics(
            {"rmse_mean": summary["rmse_mean"], "rmse_median": summary["rmse_median"], "bias_mean": summary["bias_mean"]}
        )
        peak_summary = peak_results["per_series_summary"].iloc[0]
        mlflow.log_metrics(
            {
                "peak_rmse_mean": peak_summary["rmse_mean"],
                "peak_rmse_median": peak_summary["rmse_median"],
                "peak_bias_mean": peak_summary["bias_mean"],
            }
        )
        mlflow.log_metric("beats_baseline_pct", 100 * comparison["beats_baseline"].mean())

        importances = pd.Series(final_model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
        mlflow.xgboost.log_model(final_model, name="model")

        for name, df in (
            ("window_totals", outcome["window_totals"]),
            ("peak_window_totals", outcome["peak_window_totals"]),
            ("feature_importance", importances.reset_index().rename(columns={"index": "feature", 0: "importance"})),
            ("segment_summary", outcome["segment_summary"].reset_index()),
            ("compare_to_baseline", comparison),
        ):
            path = OUTPUT_DIR / f"xgboost_v1_{name}.csv"
            df.to_csv(path, index=False)
            mlflow.log_artifact(str(path))

        pd.Series(best_params).to_json(OUTPUT_DIR / "xgboost_best_params.json")

        print("\n=== xgboost_v1 vs. seasonal_naive_genuine_91d_v2 ===")
        print(comparison.to_string(index=False))
        print("\nPer-segment RMSE/bias (post-hoc diagnostic; demand_category is also a direct model input here):")
        print(outcome["segment_summary"].to_string())
        print("\nTop features by importance:")
        print(importances.to_string())

    print(f"\nLogged under {EXPERIMENT_PATH}. See notes.md for the running log.")
