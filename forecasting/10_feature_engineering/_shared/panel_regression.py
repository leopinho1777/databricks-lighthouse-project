# %%
"""Shared fixed-effects panel regression fitting/evaluation logic for Stage 2
feature engineering (tasks 2.2-2.7). Every task calls `fit_and_evaluate()` with
its own cumulative `feature_cols` list on top of every term added by prior
tasks -- this function is never reimplemented per task, per the project's
"reuse-in-place, not reimplementation" convention (see `forecasting/OVERVIEW.md`).

Entity = the (product_variant_id, location_id) pair -- the same "series"
identity every prior forecasting stage uses as `KEYS`. Time = ISO week
(Monday-anchored), matching `03_granularity_baselines/run_baselines.py`'s
weekly branch. Target is `log1p(qty_sold_net)`; metrics are always
back-transformed via `expm1()` and computed on the raw `qty_sold_net` scale
before being compared across tasks or against `00_baseline`.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
from linearmodels.panel import PanelOLS

# Loaded by file path rather than `sys.path` + package import: this module
# lives in `forecasting/10_feature_engineering/_shared/`, which shares the
# package name `_shared` with the outer `forecasting/_shared/` -- a plain
# `sys.path.insert(...); from _shared.db_connection import ...` would silently
# resolve to whichever `_shared` package Python's import cache saw first
# (whichever stage script ran its own `sys.path.insert` earlier) instead of
# the one actually intended. Every downstream task script should import
# `query_df` from here, not touch `forecasting/_shared/db_connection.py`
# directly, so this is the only place that has to deal with the name clash.
_DB_CONNECTION_PATH = Path(__file__).resolve().parents[2] / "_shared" / "db_connection.py"
_spec = importlib.util.spec_from_file_location("forecasting_shared_db_connection", _DB_CONNECTION_PATH)
_db_connection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_connection)
query_df = _db_connection.query_df
PROD_MARTS = _db_connection.PROD_MARTS
PROD_STAGING = _db_connection.PROD_STAGING

# This developer's own scratch schema -- see _shared/db_connection.py's data
# source convention. Read-only reference data (dim_locations, stg_orders,
# etc.) used by downstream feature tasks is read from PROD_MARTS/PROD_STAGING
# instead, never from this scratch schema.
MARTS_SCRATCH = f"{_db_connection.get_scratch_schema()}.fact_demand_daily"
KEYS = ["product_variant_id", "location_id"]

# %% [markdown]
# ## 1. Load the product x location x week panel (rolled up in SQL from the
# daily prototype table, never touching `fct_sales` again -- same approach as
# `run_baselines.py`'s weekly branch).


# %%
def load_weekly_panel() -> pd.DataFrame:
    df = query_df(
        f"""
        select date_trunc('week', date_day) as period, {', '.join(KEYS)},
               sum(qty_sold_net) as qty_sold_net
        from {MARTS_SCRATCH} group by 1, 2, 3
        """
    )
    df["period"] = pd.to_datetime(df["period"]).dt.tz_localize(None)
    df["qty_sold_net"] = df["qty_sold_net"].astype("float64")
    for k in KEYS:
        df[k] = df[k].astype(str)
    return df


# %% [markdown]
# ## 2. `most_recent_complete_year()` and `compute_metrics()` -- copied
# verbatim from `03_granularity_baselines/run_baselines.py` (not imported
# across top-level stage folders, matching this project's existing
# per-stage-duplication convention).


# %%
def most_recent_complete_year(periods: pd.Series, granularity: str = "weekly") -> int:
    """A year is "complete" if its December is fully present in the data."""
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
# ## 3. Fit one cumulative PanelOLS(entity_effects=True) run and evaluate it
# on the holdout year.


# %%
def fit_and_evaluate(panel_df: pd.DataFrame, feature_cols: list[str], run_name: str) -> dict:
    """Fit `log1p(qty_sold_net) ~ feature_cols + trend` with entity fixed
    effects absorbing each (product_variant_id, location_id) series' own
    baseline level, train on `most_recent_complete_year()`'s prior years
    only, predict on the holdout year, and compute metrics on the raw
    `qty_sold_net` scale.

    `trend` (weeks elapsed since the panel's first period, continuous) is a
    STRUCTURAL CONTROL added to every call regardless of `feature_cols` --
    not a candidate feature being tested. `PanelOLS(entity_effects=True)`
    only absorbs each entity's own average level; it has nothing that
    represents a multi-year trend shared across the whole panel. This
    project's own Phase 1 finding (`forecasting/03_granularity_baselines`:
    the business grows ~14-17%/year, consistently) means any slowly-drifting
    covariate tested without a trend control would pick up that growth trend
    rather than its own genuine effect (SELIC/IPCA show an implausibly large,
    wrong-signed coefficient without it -- see
    `05_economic/05_economic_report.md`).
    A single linear term, not a per-year or per-week fixed effect, because
    (a) the growth is smooth/consistent year over year, not lumpy, so a
    linear term has the right shape, and (b) unlike a per-period fixed
    effect, it doesn't saturate the time dimension -- every other feature
    (calendar, holidays, weather, economic) still has within-year variation
    left for it to explain. `trend` gets no keep/drop verdict of its own and
    is not subject to the cumulative-retention policy documented in
    `00_feature_backlog.md` -- it makes every other feature's coefficient
    interpretable and is not a candidate feature for the production set.

    `feature_cols=[]` fits the "trend + entity fixed effects only" reference
    -- the mandatory "previous run" every cumulative task's MAPE-improvement
    delta is measured against when there is no earlier task in the chain to
    compare to (task 2.2's own reference point).

    Returns the fitted `PanelEffectsResults`, the metrics dict, the holdout
    year used, and the holdout predictions. Logging to MLflow is each calling
    task's own responsibility (tags/params differ per task).
    """
    df = panel_df.copy()
    df["entity"] = df[KEYS[0]] + "|" + df[KEYS[1]]
    df["log_qty"] = np.log1p(df["qty_sold_net"])
    df["trend"] = (df["period"] - df["period"].min()) / pd.Timedelta(weeks=1)

    holdout_year = most_recent_complete_year(df["period"])
    train_panel = df[df["period"].dt.year < holdout_year].set_index(["entity", "period"])
    holdout_panel = df[df["period"].dt.year == holdout_year].set_index(["entity", "period"])

    exog_cols = [*feature_cols, "trend"]
    model = PanelOLS(
        train_panel["log_qty"],
        train_panel[exog_cols],
        entity_effects=True,
        drop_absorbed=True,
    )
    result = model.fit(cov_type="clustered", cluster_entity=True)

    # Out-of-sample `predict()` returns only `exog @ params` -- linearmodels
    # explicitly does not add the entity fixed effect back in for new data
    # (see PanelResults.predict docstring: "effects ... not available for
    # out-of-sample predictions"). Each entity's own effect is constant
    # across its training weeks, so it's added back manually here using the
    # holdout year's *same* entities (this is a same-series, later-weeks
    # holdout, not a forecast for brand-new products/locations).
    oos_fitted = result.predict(exog=holdout_panel[exog_cols]).reset_index()
    entity_effect = (
        result.estimated_effects.reset_index().groupby("entity", as_index=False)["estimated_effects"].mean()
    )

    merged = oos_fitted.merge(entity_effect, on="entity", how="left")
    merged["estimated_effects"] = merged["estimated_effects"].fillna(0.0)
    merged["log_qty_pred"] = merged["predictions"] + merged["estimated_effects"]
    merged["qty_sold_net_pred"] = np.expm1(merged["log_qty_pred"]).clip(lower=0)

    actual = holdout_panel.reset_index()[["entity", "period", "qty_sold_net"]]
    joined = actual.merge(merged[["entity", "period", "qty_sold_net_pred"]], on=["entity", "period"], how="left")
    metrics = compute_metrics(joined["qty_sold_net"], joined["qty_sold_net_pred"])

    return {
        "run_name": run_name,
        "result": result,
        "metrics": metrics,
        "holdout_year": holdout_year,
        "predictions": joined,
    }


# %% [markdown]
# ## 4. MLflow bootstrap -- same credential/tracking-URI pattern as
# `09_baseline_close_out/log_baseline_to_mlflow.py`, centralized here since
# every task 2.2-2.7 script repeats it identically.


# %%
def init_mlflow_experiment(experiment_path: str = "/Shared/01_feature_iteration"):
    import os
    import sys

    import mlflow

    # mlflow prints a run-URL courtesy message containing an emoji on run
    # completion; Windows consoles default stdout to cp1252, which can't
    # encode it and raises UnicodeEncodeError right as the `with
    # mlflow.start_run(...)` block exits -- after every param/metric/tag is
    # already logged, but before the script can continue. Widen stdout to
    # utf-8 so that print succeeds instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    profile = _db_connection._load_dev_profile()
    os.environ.setdefault("DATABRICKS_HOST", f"https://{profile['host']}")
    if profile.get("token"):
        os.environ.setdefault("DATABRICKS_TOKEN", profile["token"])

    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(experiment_path)
    return mlflow
