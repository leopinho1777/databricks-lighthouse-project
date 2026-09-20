# %%
"""Stage 3 (task 3.n) -- fixed-effects panel regression scored under the shared protocol.

The model itself is Stage 2's: `log1p(qty) ~ month_2..month_12 + trend` with
entity fixed effects per (product_variant_id, location_id) series. What is new
here is the evaluation, and that is the whole point of this script: Stage 2
measured this regression as weekly MAPE against a single holdout year and
against its own no-features reference, so its numbers cannot be compared with
`00_baseline`'s champion. This script refits the same specification once per
91-day window and scores it through `experiments/_shared/evaluate.py`, so the
result sits on the same ruler as every other Stage 3 candidate.

Three choices worth knowing before reading the code:

1. **Target is `qty_sold_gross`, not Stage 2's `qty_sold_net`.** The protocol
   scores against the Phase 1 close-out's actuals, which are
   `SUM(quantity) WHERE order_status IN ('paid','confirmed')` straight from
   `fct_sales` -- the same definition `fact_demand_daily.qty_sold_gross` is
   built from. Training on net (gross minus returns) while being scored on
   gross would build in a systematic under-forecast that has nothing to do
   with the model.

2. **Weekly fit, daily proration into the window.** ISO weeks are
   Monday-anchored and the cutoffs are not (2024-12-31 is a Tuesday), so a
   week can straddle the window boundary. Each predicted week contributes
   `pred_week * days_inside_window / 7`. Assigning whole weeks to whichever
   side they mostly fall on would shift the totals and make `actual_total`
   drift from the baseline's.

3. **`expm1` of a log-scale prediction is a median, not a mean.** On an
   intermittent catalog this under-forecasts. It is a known retransformation
   bias with a known correction (Duan's smearing estimator, `SMEARING=1`); the
   uncorrected and smearing runs are kept side by side so the effect is visible
   per window.
"""

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from linearmodels.panel import PanelOLS

_EXPERIMENTS = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# The shared protocol and the reproducibility helpers, imported rather than
# reimplemented -- the entire reason both modules exist.
sys.path.insert(0, str(_EXPERIMENTS / "_shared"))
from evaluate import compare_to_baseline, evaluate, get_cutoffs, to_category_level  # noqa: E402
from repro import get_library_versions, get_table_version  # noqa: E402

# Loaded by file path, not by package name: three directories in this repo are
# named `_shared`, so `import _shared...` resolves to whichever one Python's
# import cache saw first. Same technique `evaluate.py` and `repro.py` use.
_DB_PATH = _EXPERIMENTS.parent / "_shared" / "db_connection.py"
_spec = importlib.util.spec_from_file_location("db_connection_eva_regression", _DB_PATH)
_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db)
query_df = _db.query_df

SCRATCH_TABLE = f"{_db.get_scratch_schema()}.fact_demand_daily"
KEYS = ["product_variant_id", "location_id"]
HORIZON_DAYS = 91
# The shared Stage 3 experiment -- the same one `random_forest_baseline` logs
# to, which is the entire point of a shared experiment: one screen ranking
# every candidate model instead of one drawer per person.
EXPERIMENT = "/Shared/02_model_comparison"

# Duan's smearing estimator, off by default so the uncorrected run stays on
# record next to it. Fitting on log1p(y) and predicting expm1(x'b) estimates
# the conditional MEDIAN, not the mean: the uncorrected run under-forecasts
# total demand by ~71%. Smearing multiplies the prediction
# by the average exponentiated training residual, the standard non-parametric
# correction (Duan 1983) -- it assumes the residual distribution is the same
# out of sample, which is why it is tested rather than assumed.
APPLY_SMEARING = os.environ.get("SMEARING", "0") == "1"
RUN_NAME = "panel_regression_fe_trend_month" + ("_smearing" if APPLY_SMEARING else "")
MONTH_COLS = [f"month_{m}" for m in range(2, 13)]  # January is the reference level
EXOG_COLS = [*MONTH_COLS, "trend"]

# Set SAMPLE_ENTITIES=200 for a fast pipeline smoke test before the full run.
SAMPLE_ENTITIES = int(os.environ.get("SAMPLE_ENTITIES", "0"))

# %% [markdown]
# ## 1. The dense weekly panel
#
# Rolled up from the daily prototype table, which is already zero-filled. The
# zeros are not optional: a panel built from sales rows alone would drop every
# quiet week and the model would fit the level of "weeks that sold something".


# %%
def load_weekly_panel() -> pd.DataFrame:
    df = query_df(
        f"""
        select date_trunc('week', date_day) as period,
               {", ".join(KEYS)},
               sum(qty_sold_gross) as qty
        from {SCRATCH_TABLE}
        group by 1, 2, 3
        """
    )
    df["period"] = pd.to_datetime(df["period"]).dt.tz_localize(None)
    df["qty"] = df["qty"].astype("float64")
    for k in KEYS:
        df[k] = df[k].astype(str)

    df["entity"] = df[KEYS[0]] + "|" + df[KEYS[1]]
    df["log_qty"] = np.log1p(df["qty"])
    # Month dummies and trend are calendar facts, known in advance for any
    # future date -- which is what makes a genuinely held-static 91-day
    # forecast possible with this feature set.
    for m in range(2, 13):
        df[f"month_{m}"] = (df["period"].dt.month == m).astype("float64")
    df["trend"] = (df["period"] - df["period"].min()) / pd.Timedelta(weeks=1)
    return df


# %% [markdown]
# ## 2. One window: fit on the past, predict forward, prorate into the window


# %%
def future_feature_frame(entities: np.ndarray, window_start: pd.Timestamp, window_end: pd.Timestamp, panel_start: pd.Timestamp) -> pd.DataFrame:
    """Every (entity, week) pair whose week overlaps the window, with features
    rebuilt from the calendar rather than read from the table -- the forecast
    must not touch any row dated after the cutoff, not even to look up a date."""
    first_monday = window_start - pd.Timedelta(days=window_start.weekday())
    weeks = pd.date_range(first_monday, window_end, freq="W-MON")

    frame = pd.MultiIndex.from_product([entities, weeks], names=["entity", "period"]).to_frame(index=False)
    for m in range(2, 13):
        frame[f"month_{m}"] = (frame["period"].dt.month == m).astype("float64")
    frame["trend"] = (frame["period"] - panel_start) / pd.Timedelta(weeks=1)
    return frame


# %%
def forecast_window(panel: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Refit on data up to `cutoff` only, then predict the 91 days after it."""
    window_start = cutoff + pd.Timedelta(days=1)
    window_end = cutoff + pd.Timedelta(days=HORIZON_DAYS)

    # A week is training data only if it closed on or before the cutoff --
    # keeping the straddling week would leak days from inside the window.
    train = panel[panel["period"] + pd.Timedelta(days=6) <= cutoff]
    train_idx = train.set_index(["entity", "period"])

    model = PanelOLS(train_idx["log_qty"], train_idx[EXOG_COLS], entity_effects=True, drop_absorbed=True)
    result = model.fit(cov_type="clustered", cluster_entity=True)

    future = future_feature_frame(train["entity"].unique(), window_start, window_end, panel["period"].min())
    future_idx = future.set_index(["entity", "period"])

    # `predict()` returns only `exog @ params`: linearmodels does not add the
    # entity effect back for out-of-sample rows (see PanelResults.predict).
    # Each entity's effect is constant across its training weeks, so it is
    # merged back manually -- same series, later weeks, not new entities.
    predicted = result.predict(exog=future_idx[EXOG_COLS]).reset_index()
    effects = result.estimated_effects.reset_index().groupby("entity", as_index=False)["estimated_effects"].mean()

    merged = predicted.merge(effects, on="entity", how="left")
    merged["estimated_effects"] = merged["estimated_effects"].fillna(0.0)
    log_pred = merged["predictions"] + merged["estimated_effects"]
    if APPLY_SMEARING:
        # E[y] = exp(x'b) * E[exp(residual)] - 1, with the expectation estimated
        # by the training residuals themselves rather than assumed lognormal.
        smearing = float(np.mean(np.exp(result.resids)))
        merged["qty_week"] = (np.exp(log_pred) * smearing - 1).clip(lower=0)
    else:
        merged["qty_week"] = np.expm1(log_pred).clip(lower=0)

    # Prorate each week by how many of its days actually fall inside the window.
    week_end = (merged["period"] + pd.Timedelta(days=6)).clip(upper=window_end)
    week_start = merged["period"].clip(lower=window_start)
    days_inside = (week_end - week_start).dt.days + 1
    merged["pred"] = merged["qty_week"] * days_inside.clip(lower=0, upper=7) / 7

    pred = merged.groupby("entity", as_index=False)["pred"].sum()
    pred[KEYS[0]] = pred["entity"].str.split("|").str[0]
    pred[KEYS[1]] = pred["entity"].str.split("|").str[1]
    return pred[[*KEYS, "pred"]]


# %%
def actuals_for_window(cutoff: pd.Timestamp) -> pd.DataFrame:
    """Same definition as `09_baseline_close_out`'s actuals (paid/confirmed
    quantity), read from the column of the prototype table built from it."""
    start = (cutoff + pd.Timedelta(days=1)).date()
    end = (cutoff + pd.Timedelta(days=HORIZON_DAYS)).date()
    df = query_df(
        f"""
        select {", ".join(KEYS)}, sum(qty_sold_gross) as actual
        from {SCRATCH_TABLE}
        where date_day between date'{start}' and date'{end}'
        group by 1, 2
        """
    )
    for k in KEYS:
        df[k] = df[k].astype(str)
    df["actual"] = df["actual"].astype("float64")
    return df


# %% [markdown]
# ## 3. MLflow
#
# Metrics are logged per window with `step`, never as a single averaged
# number, because the protocol reports per window -- an average would hide
# that window 3 (the off-season) behaves differently from the peak-season
# ones, which is exactly what the baseline's 78-88% WAPE spread shows.


# %%
def log_to_mlflow(portfolio: pd.DataFrame, summary: pd.DataFrame, comparison: pd.DataFrame, n_series: int) -> None:
    import mlflow

    # Point the SDK at the same workspace `db_connection.py` authenticates
    # against. Without this, `databricks-cli` auth resolves whichever profile
    # is default in ~/.databrickscfg, which may be a different workspace, and
    # the run would land there silently.
    profile = _db._load_dev_profile()
    os.environ["DATABRICKS_HOST"] = f"https://{profile['host']}"
    if profile.get("token"):
        os.environ["DATABRICKS_TOKEN"] = profile["token"]

    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(EXPERIMENT)

    with mlflow.start_run(run_name=RUN_NAME):
        mlflow.log_params(
            {
                "model": "PanelOLS entity effects",
                "target": "log1p(qty_sold_gross)",
                "features": ",".join(EXOG_COLS),
                "fit_grain": "weekly (ISO, Monday-anchored)",
                "score_grain": f"{HORIZON_DAYS}-day window total per series",
                "n_series": n_series,
                "n_windows": len(portfolio),
                "refit_per_window": True,
                "feature_set_source": "10_frozen_feature_set.md",
            }
        )

        for step, row in enumerate(portfolio.itertuples(index=False)):
            mlflow.log_metric("wape_pct", row.wape_pct, step=step)
            mlflow.log_metric("bias", row.bias, step=step)
            mlflow.log_metric("forecast_total", row.forecast_total, step=step)

        mlflow.log_metric("wape_pct_mean", portfolio["wape_pct"].mean())
        mlflow.log_metric("rmse_mean", summary.loc[0, "rmse_mean"])
        mlflow.log_metric("bias_mean_per_series", summary.loc[0, "bias_mean"])
        mlflow.log_metric("windows_beating_baseline", int(comparison["beats_baseline"].sum()))

        # Reproducibility tags, via the shared helper rather than hand-rolled.
        mlflow.set_tags({**get_table_version(SCRATCH_TABLE), **get_library_versions(["linearmodels", "pandas", "numpy"])})
        mlflow.log_artifacts(str(OUTPUT_DIR))
        print(f"Logged '{RUN_NAME}' to {EXPERIMENT}")


# %% [markdown]
# ## 4. Run every window and score through the shared protocol

# %%
if __name__ == "__main__":
    panel = load_weekly_panel()
    if SAMPLE_ENTITIES:
        keep = pd.Index(sorted(panel["entity"].unique())[:SAMPLE_ENTITIES])
        panel = panel[panel["entity"].isin(keep)]
        print(f"SMOKE TEST: {SAMPLE_ENTITIES} entities only -- results are not comparable to the baseline.")
    print(f"Panel: {len(panel):,} rows, {panel['entity'].nunique():,} series, {panel['period'].min().date()} to {panel['period'].max().date()}")

    frames = []
    for cutoff in get_cutoffs():
        pred = forecast_window(panel, cutoff)
        actual = actuals_for_window(cutoff)
        # In smoke mode the panel is a subset but the actuals query is not --
        # scoring 200 series' predictions against the whole catalog's demand
        # would report a meaningless ~100% WAPE.
        if SAMPLE_ENTITIES:
            actual = actual[(actual[KEYS[0]] + "|" + actual[KEYS[1]]).isin(panel["entity"].unique())]
        window = actual.merge(pred, on=KEYS, how="left")
        window["pred"] = window["pred"].fillna(0.0)
        window["cutoff"] = cutoff
        frames.append(window)
        print(f"  {cutoff.date()}: actual {window['actual'].sum():,.0f} | pred {window['pred'].sum():,.0f}")

    window_totals = pd.concat(frames, ignore_index=True)
    results = evaluate(window_totals)

    print("\n=== Portfolio, per window (SKU x location) ===")
    print(results["portfolio"].to_string(index=False))
    print("\n=== Per series, across the four windows ===")
    print(results["per_series_summary"].to_string(index=False))
    print("\n=== Against the seasonal naive champion ===")
    comparison = compare_to_baseline(results["portfolio"])
    print(comparison.to_string(index=False))

    by_category = evaluate(to_category_level(window_totals), keys=["category_name", "location_id"])
    print("\n=== Portfolio, per window (category x location) ===")
    print(by_category["portfolio"].to_string(index=False))

    print("\n=== Reproducibility tags ===")
    print(get_table_version(SCRATCH_TABLE))
    print(get_library_versions(["linearmodels", "pandas", "numpy"]))

    if not SAMPLE_ENTITIES:
        # Prefixed by run name so the smearing run does not overwrite the
        # uncorrected one -- the pair is the comparison.
        window_totals.to_csv(OUTPUT_DIR / f"{RUN_NAME}_window_totals.csv", index=False)
        results["portfolio"].to_csv(OUTPUT_DIR / f"{RUN_NAME}_portfolio_metrics.csv", index=False)
        results["per_series"].to_csv(OUTPUT_DIR / f"{RUN_NAME}_per_series_metrics.csv", index=False)
        comparison.to_csv(OUTPUT_DIR / f"{RUN_NAME}_baseline_comparison.csv", index=False)
        by_category["portfolio"].to_csv(OUTPUT_DIR / f"{RUN_NAME}_portfolio_metrics_category.csv", index=False)
        print(f"\nSaved to {OUTPUT_DIR}")

        # Logged only on a full run: a 200-series smoke test is not a result
        # anyone should find sitting in the shared experiment.
        log_to_mlflow(results["portfolio"], results["per_series_summary"], comparison, panel["entity"].nunique())
