# %% [markdown]
# # Task 3.5 — SARIMA on the frozen Stage 2 feature set (statistical benchmark)
#
# Fits one `SARIMAX` per `(product_variant_id, location_id)` series -- unlike RF/XGBoost's
# single pooled panel fit, SARIMA is inherently per-series ("the product's own historical
# values and seasonal patterns", per the tracker). Full catalog (6,054 series), not a
# subsample: `compare_to_baseline()` needs the same-catalog `actual_total` the baseline was
# computed against, so a partial-catalog run would trip its drift check by construction.
#
# Trend handling is SARIMA-specific (`10_frozen_feature_set.md` §2): growth goes through the
# model's own machinery, not a `trend` regressor the way RF/XGBoost use it. Two variants run:
# non-seasonal differencing (`d=1`) and `d=0` with a constant trend term (`sarima_d0_trend`,
# the better of the two). Annual seasonality goes through seasonal differencing
# (`D=1, s=52` at weekly grain).
# `month_2`..`month_12` dummies still enter as `exog` alongside that differencing -- they
# capture a different thing (deterministic calendar shape) than `D=1` does (stochastic
# year-over-year seasonal drift a fixed dummy can't adapt to), so both are kept, not
# either/or. See `README.md` for the full order-selection reasoning.
#
# Scored against the Stage 3 protocol (`experiments/_shared/evaluate.py`): refit per
# rolling-origin cutoff, sum weekly forecasts into a 91-day window total per series,
# compare against the `seasonal_naive_genuine_91d_v2` champion.

# %%
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.statespace.sarimax import SARIMAX

FORECASTING = Path(__file__).resolve().parents[2]

# Module-name imports by path, not `import _shared` -- the repo has three directories
# named `_shared`; a package-name import would resolve to whichever one Python's import
# cache saw first. Same technique every other Stage 2/3 script already uses.
sys.path.insert(0, str(FORECASTING / "experiments" / "_shared"))
from evaluate import compare_to_baseline, evaluate, get_cutoffs  # noqa: E402
from repro import get_library_versions, get_table_version  # noqa: E402

sys.path.insert(0, str(FORECASTING / "10_feature_engineering" / "_shared"))
from panel_regression import MARTS_SCRATCH, init_mlflow_experiment, load_weekly_panel  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

EXPERIMENT_PATH = "/Shared/02_model_comparison"
DEMAND_CLASSIFICATION_CSV = FORECASTING / "04_demand_classification" / "output" / "demand_classification.csv"

HORIZON_WEEKS = 13  # 91 days; exog (month dummies) is known in advance for any future week ->
# a single get_forecast(steps=13) call covers the whole horizon, no recursive multi-step forecasting.
STRADDLE_LAG = pd.Timedelta(days=6)  # see `run_walk_forward` docstring -- identical rationale/value
# to `eros_randomforest/train_random_forest.py`'s, copied verbatim rather than re-derived.
TRAIN_END = pd.Timestamp("2024-12-31")  # fixed, matches run_genuine_baseline.py's peak-month reference period

MONTH_COLS = [f"month_{m}" for m in range(2, 13)]
SEASONAL_PERIOD = 52  # weekly grain -> annual seasonality
MAXITER = 50  # bounds per-fit optimizer cost across a 24,216-fit run; see README.md's timed-pilot section

# %% [markdown]
# ## 0. Optional smoke-test knob
#
# `SAMPLE_ENTITIES=200` restricts to a small, deterministic entity subset for a fast
# pipeline check before the full run -- same convention `eva_regression/run_panel_regression.py`
# uses. Results from a sampled run are NOT comparable to the baseline (which is scored
# against the full catalog) and `compare_to_baseline()`'s drift warning is expected to fire.

# %%
import os  # noqa: E402

SAMPLE_ENTITIES = int(os.environ.get("SAMPLE_ENTITIES", "0"))

# Module-level globals populated by `_setup()`, not at import time -- see that function's
# docstring for why (loky worker re-import safety). Declared here as `None` so static
# analysis and IDEs see them; every entry point (`__main__` below, or a test/smoke harness)
# must call `_setup()` before using `panel`/`PEAK_MONTHS`/`_segments`/`EXEMPLAR_ENTITIES`.
panel = None
PEAK_MONTHS = None
_segments = None
EXEMPLAR_ENTITIES = None


def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Frozen feature set only (`10_frozen_feature_set.md`): month_2..month_12 dummies.

    No `trend` column here, unlike every other Stage 3 model -- SARIMA handles the same
    ~14-17%/year growth via non-seasonal differencing (`d=1` in `order`) instead of a
    regressor, per the frozen-feature-set doc's explicit ARIMA/SARIMA carve-out.
    """
    df = df.copy()
    dummies = pd.get_dummies(df["period"].dt.month, prefix="month")
    for c in MONTH_COLS:
        if c not in dummies:
            dummies[c] = 0
    df = pd.concat([df, dummies[MONTH_COLS].astype("float64")], axis=1)
    return df


def _calendar_lookup(periods: pd.DatetimeIndex) -> pd.DataFrame:
    """Period -> month-dummy row. Calendar exog depends only on the period, not the
    entity, so this is computed once per cutoff and shared across every series' fit
    instead of rebuilt per series."""
    frame = add_calendar(pd.DataFrame({"period": periods}))
    return frame.set_index("period")[MONTH_COLS]


def _pivot_qty(df: pd.DataFrame, periods: pd.DatetimeIndex) -> pd.DataFrame:
    """entity x period matrix of qty_sold_net, reindexed to a dense, ordered period axis.

    `load_weekly_panel()` is already a dense global spine (every entity present at every
    period back to 2020-01-01, per `fact_demand_daily`'s build) -- `fill_value=0.0` here is
    a defensive reindex, not expected to paper over real gaps.
    """
    wide = df.pivot_table(
        index=["product_variant_id", "location_id"], columns="period", values="qty_sold_net", aggfunc="sum", fill_value=0.0
    )
    return wide.reindex(columns=periods, fill_value=0.0)


def _select_exemplars(df: pd.DataFrame) -> dict:
    """2-3 fixed series whose final-cutoff fitted model gets logged as an MLflow artifact --
    not all 6,054, which would be impractical artifact bloat for little benefit (per-series
    fit diagnostics are already captured in fit_diagnostics.csv). Picked once, by volume,
    from demand_classification.csv: the catalog's single highest-volume series overall, plus
    the highest-volume series in each of the two segments present in this catalog
    (Intermittent/Lumpy -- see `04_demand_classification`), so the exemplars are reproducible
    and documented rather than arbitrary."""
    exemplars = {}
    top_overall = df.sort_values("total_qty_sold_net", ascending=False).iloc[0]
    exemplars["top_volume"] = (top_overall["product_variant_id"], top_overall["location_id"])
    for cat in ("intermittent", "lumpy"):
        subset = df[df["category"] == cat]
        if len(subset):
            row = subset.sort_values("total_qty_sold_net", ascending=False).iloc[0]
            exemplars[cat] = (row["product_variant_id"], row["location_id"])
    return exemplars


def _setup(sample_entities: int = 0) -> None:
    """Populate the module-level `panel`/`PEAK_MONTHS`/`_segments`/`EXEMPLAR_ENTITIES`
    globals -- the warehouse query and CSV read live here, NOT at bare module-import time.

    Why: joblib's default `Parallel` backend (`loky`, process-based -- needed for real
    multi-core speedup; a `backend="threading"` alternative was tried first and measured,
    via a direct serial-vs-threaded timing comparison, to give NO real speedup here --
    0.84x, i.e. slightly worse than serial -- because SARIMAX.fit()'s scipy.optimize loop
    doesn't release the GIL enough for this per-fit problem size) spawns worker processes
    that reconstruct this module by re-running its top-level code -- a standard requirement
    of Python's "spawn" multiprocessing start method. Anything at bare module
    level (imports, constants, function defs) is cheap and safe to repeat per worker.
    Anything with a side effect -- especially `load_weekly_panel()`'s warehouse query --
    must NOT be at bare module level, or every worker process independently re-runs it on
    startup. Only the parent process calls this, from `if __name__ == "__main__":` (or a
    test/smoke harness that stubs `load_weekly_panel`).
    """
    global panel, PEAK_MONTHS, _segments, EXEMPLAR_ENTITIES

    panel = load_weekly_panel()  # period (Monday-anchored weekly Timestamp), product_variant_id (str), location_id (str), qty_sold_net (float)
    if sample_entities:
        entities = panel[["product_variant_id", "location_id"]].drop_duplicates()
        keep = entities.sort_values(["product_variant_id", "location_id"]).head(sample_entities)
        panel = panel.merge(keep, on=["product_variant_id", "location_id"], how="inner")
        print(f"SMOKE TEST: {sample_entities} entities only -- results are not comparable to the baseline.")

    # Peak months: computed ONCE, from data up to the fixed TRAIN_END only -- matching
    # run_genuine_baseline.py's actual approach (a single value reused across all 4 cutoffs
    # there), so this run's peak-season slice stays defined the same way as the champion
    # baseline's peak_season CSV. Copied verbatim from `train_random_forest.py`.
    train_end_data = panel[panel["period"] <= TRAIN_END - STRADDLE_LAG]
    monthly = train_end_data.groupby([train_end_data["period"].dt.year, train_end_data["period"].dt.month])["qty_sold_net"].sum()
    avg_by_month = monthly.groupby(level=1).mean()
    PEAK_MONTHS = sorted(avg_by_month[avg_by_month > avg_by_month.mean()].index.tolist())
    print(f"Peak-season months (from data <= {TRAIN_END.date()}): {PEAK_MONTHS}")

    classification = pd.read_csv(
        DEMAND_CLASSIFICATION_CSV,
        usecols=["product_variant_id", "location_id", "category", "total_qty_sold_net"],
        dtype={"product_variant_id": str, "location_id": str},
    )
    _segments = classification[["product_variant_id", "location_id", "category"]]
    EXEMPLAR_ENTITIES = _select_exemplars(classification)
    print(f"Exemplar entities for MLflow model-artifact logging: {EXEMPLAR_ENTITIES}")


# %% [markdown]
# ## 2. Order-selection diagnostics (offline, run once via `--diagnose`, not part of the
# production loop)
#
# `d`: checked, not assumed, via ADF on the portfolio-aggregate AND a stratified per-series
# sample -- aggregation can behave differently from individual series (this catalog's
# per-series demand is 92.9%-zero at weekly grain per `10_frozen_feature_set.md`, nothing
# like the smooth aggregate), so both are checked before committing to a catalog-wide `d`.
# `D=1, s=52` is applied directly, not diagnosed -- the annual-seasonality finding is already
# independently confirmed twice in this repo (see module docstring). `p, q` are chosen from a
# small, fixed AIC comparison on the portfolio-aggregate series, not searched per series.


# %%
def _stratified_entity_sample(panel_df: pd.DataFrame, segments_df: pd.DataFrame, n_per_stratum: int = 5, seed: int = 42) -> pd.DataFrame:
    """~20-30 series stratified by segment (Intermittent/Lumpy) x volume (below/above the
    segment's own median total qty), for the per-series ADF check below -- not a random
    catalog-wide sample, so both segments and both volume levels are represented regardless
    of the 96.8%/3.2% Intermittent/Lumpy imbalance."""
    volumes = panel_df.groupby(["product_variant_id", "location_id"])["qty_sold_net"].sum().rename("total_qty").reset_index()
    merged = volumes.merge(segments_df, on=["product_variant_id", "location_id"], how="left")
    merged["category"] = merged["category"].fillna("unknown")

    strata = []
    for _, group in merged.groupby("category"):
        median = group["total_qty"].median()
        for stratum in (group[group["total_qty"] <= median], group[group["total_qty"] > median]):
            if len(stratum):
                strata.append(stratum.sample(n=min(n_per_stratum, len(stratum)), random_state=seed))
    return pd.concat(strata, ignore_index=True) if strata else merged.sample(n=min(20, len(merged)), random_state=seed)


def diagnose_orders(panel_df: pd.DataFrame, segments_df: pd.DataFrame) -> None:
    from statsmodels.graphics.tsaplots import acf, pacf
    from statsmodels.tsa.stattools import adfuller

    portfolio = panel_df.groupby("period")["qty_sold_net"].sum().sort_index()
    log_portfolio = np.log1p(portfolio)

    # Both regression specs checked: "c" (constant only) is statsmodels' default and doesn't
    # explicitly account for a deterministic trend; "ct" (constant + linear trend) is the
    # more appropriate test given this project's own twice-confirmed ~14-17%/year growth
    # (03_granularity_baselines; 10_feature_engineering's own `trend` coefficient, t~32-50) --
    # a "c"-only reading would understate that here.
    print("Portfolio-aggregate ADF, levels (log1p):")
    for label, reg in (("c (constant only)", "c"), ("ct (constant + trend)", "ct")):
        stat, p, lags, *_ = adfuller(log_portfolio, regression=reg)
        print(f"  regression={label}: stat={stat:.3f}, p={p:.4f}, lags={lags}")

    diff1 = log_portfolio.diff().dropna()
    adf_diff1 = adfuller(diff1)
    print(f"Portfolio-aggregate ADF, diff(1): stat={adf_diff1[0]:.3f}, p={adf_diff1[1]:.4f}")

    print(f"\nACF(diff1)[1:8]: {np.round(acf(diff1, nlags=8)[1:], 3)}")
    print(f"PACF(diff1)[1:8]: {np.round(pacf(diff1, nlags=8)[1:], 3)}")

    print("\nAIC over a small (p,q) candidate set at d=1, D=0 (no seasonal term here -- this")
    print("step is only about the non-seasonal p,q order, D/s are applied directly per the")
    print("frozen-feature-set doc, not diagnosed):")
    for p, q in ((0, 1), (1, 0), (1, 1)):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = SARIMAX(log_portfolio, order=(p, 1, q), enforce_stationarity=False, enforce_invertibility=False).fit(
                maxiter=MAXITER, disp=False
            )
        print(f"  order=({p},1,{q}): AIC={fit.aic:.1f}")

    # Per-series check -- the part the earlier design pass called for but the first cut of
    # this function skipped. Individual series are heavily zero-inflated/intermittent, unlike
    # the smooth portfolio aggregate, so this is checked directly rather than assumed to
    # mirror the aggregate's result.
    sample = _stratified_entity_sample(panel_df, segments_df)
    print(f"\nPer-series ADF (levels, log1p), {len(sample)} series stratified by segment x volume:")
    n_reject, n_fail, n_error = 0, 0, 0
    for _, row in sample.iterrows():
        key = (row["product_variant_id"], row["location_id"])
        series = panel_df[(panel_df["product_variant_id"] == key[0]) & (panel_df["location_id"] == key[1])].sort_values("period")
        y = np.log1p(series["qty_sold_net"].to_numpy())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                stat, p, *_ = adfuller(y)
            if p < 0.05:
                verdict, n_reject = "reject H0 (stationary)", n_reject + 1
            else:
                verdict, n_fail = "fail to reject H0 (unit root)", n_fail + 1
            print(f"  {key} [{row['category']}, total_qty={row['total_qty']:.0f}]: stat={stat:.3f}, p={p:.4f} -> {verdict}")
        except Exception as exc:
            n_error += 1
            print(f"  {key} [{row['category']}, total_qty={row['total_qty']:.0f}]: ADF errored -- {str(exc)[:100]}")
    print(f"\nSummary: {n_reject}/{len(sample)} reject H0 (stationary at levels), {n_fail}/{len(sample)} fail to reject (favor differencing), {n_error} errored.")
    print("\nThese findings are recorded in README.md; this diagnostic is not re-run per production execution.")


# %% [markdown]
# ## 3. Per-series fit
#
# One `SARIMAX` fit per entity per cutoff (24,216 fits for the full catalog across 4
# cutoffs). `enforce_stationarity=False, enforce_invertibility=False, simple_differencing=True`
# and a capped `maxiter` bound per-fit cost and avoid hard failures on the catalog's many
# near-flat/near-zero series (96.8% Intermittent, 92.9%-zero at this grain).
#
# Predetermined fallback on any fit failure: forecast 0 for the horizon (mirrors
# `train_random_forest.py`'s documented "no history -> forecast 0" convention) -- the
# failure itself is recorded in `fit_diagnostics.csv`, not silently swallowed.
#
# "converged" here means "the fit completed without a ConvergenceWarning or exception" --
# statsmodels doesn't expose a single, optimizer-agnostic convergence flag on the results
# object, so a raised ConvergenceWarning (caught explicitly) is treated as the signal.


# %%
def fit_one_series(
    entity_key: tuple,
    y: np.ndarray,
    exog_train: np.ndarray,
    exog_future: np.ndarray,
    order: tuple,
    seasonal_order: tuple,
    trend: str = None,
) -> dict:
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            model = SARIMAX(
                y,
                exog=exog_train,
                order=order,
                seasonal_order=seasonal_order,
                trend=trend,
                enforce_stationarity=False,
                enforce_invertibility=False,
                simple_differencing=True,
            )
            fitted = model.fit(maxiter=MAXITER, disp=False)
            converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
        forecast = fitted.get_forecast(steps=exog_future.shape[0], exog=exog_future)
        pred_weekly = np.clip(np.asarray(forecast.predicted_mean), a_min=0, a_max=None)

        # Sanity bound, not just a lower clip: `enforce_stationarity=False` lets the optimizer
        # pick an explosive AR root for a small minority of series, which compounds
        # exponentially over a 13-step forecast and produces astronomically large (but still
        # finite, non-NaN -- no exception raised) predictions. Found via a real full-catalog
        # run: only 5/24,216 fits did this, but portfolio WAPE sums absolute error over total
        # actual demand, so a handful of ~1e150+ predictions completely corrupts the metric
        # despite the other 24,211 being reasonable. Treated as a fit failure (existing
        # fallback path), not silently trusted, same principle as the exception-based fallback
        # below -- a "successful" fit can still produce garbage output.
        history_max = float(np.max(y)) if y.size else 0.0
        sane_cap = max(1000.0, 100.0 * history_max)
        if not np.all(np.isfinite(pred_weekly)) or np.any(pred_weekly > sane_cap):
            raise ValueError(
                f"unstable forecast: max pred={np.nanmax(pred_weekly):.3e} exceeds sane cap "
                f"{sane_cap:.1f} (100x series' own historical peak week={history_max:.1f})"
            )
        return {
            "entity": entity_key,
            "pred_weekly": pred_weekly,
            "aic": float(fitted.aic),
            "converged": converged,
            "fallback": False,
            "error": None,
        }
    except Exception as exc:  # a single bad series must not crash the 24,216-fit run
        return {
            "entity": entity_key,
            "pred_weekly": np.zeros(exog_future.shape[0]),
            "aic": np.nan,
            "converged": False,
            "fallback": True,
            "error": str(exc)[:300],
        }


# %% [markdown]
# ## 4. Walk-forward loop
#
# Weeks are Monday-anchored. The protocol's 4 cutoffs are all Tuesdays (91 = 13*7, so the
# weekday never shifts), so the week containing each cutoff straddles it -- excluded from
# both train and the scored horizon via `STRADDLE_LAG`, identical rationale to
# `train_random_forest.py`'s `run_walk_forward` docstring (see that file for the full
# explanation; not re-derived here).


# %%
def run_walk_forward(order: tuple, seasonal_order: tuple, run_name: str, trend: str = None) -> dict:
    cutoffs = get_cutoffs()
    main_rows, peak_rows, diag_rows = [], [], []
    exemplar_fits = {}

    for cutoff in cutoffs:
        train = panel[panel["period"] <= cutoff - STRADDLE_LAG]
        train_periods = pd.date_range(train["period"].min(), cutoff - STRADDLE_LAG, freq="W-MON")
        horizon_periods = pd.date_range(cutoff + pd.Timedelta(days=1), periods=HORIZON_WEEKS, freq="W-MON")
        exog_lookup = _calendar_lookup(train_periods.union(horizon_periods))
        exog_train = exog_lookup.loc[train_periods].to_numpy(dtype="float64")
        exog_future = exog_lookup.loc[horizon_periods].to_numpy(dtype="float64")
        is_peak = pd.Series(horizon_periods).dt.month.isin(PEAK_MONTHS).to_numpy()

        wide = _pivot_qty(train, train_periods)
        entities = wide.index.tolist()
        y_matrix = wide.to_numpy(dtype="float64")
        entity_pos = {e: i for i, e in enumerate(entities)}

        # Default (process-based, "loky") backend, not "threading": measured directly (serial
        # vs. threaded timing on an identical entity batch) that threading gives NO real
        # speedup on this workload -- 0.84x, i.e. slightly worse than serial, because
        # SARIMAX.fit()'s scipy.optimize loop doesn't release the GIL enough at this per-fit
        # problem size. Process-based parallelism requires the warehouse-hitting setup to be
        # out of bare module scope (see `_setup()`'s docstring for why) -- that's done, so
        # this is safe.
        fit_results = Parallel(n_jobs=-1)(
            delayed(fit_one_series)(entities[i], y_matrix[i], exog_train, exog_future, order, seasonal_order, trend)
            for i in range(len(entities))
        )

        pred_records, diag_records = [], []
        for r in fit_results:
            pv, loc = r["entity"]
            pred_records.append(
                {
                    "product_variant_id": pv,
                    "location_id": loc,
                    "cutoff": cutoff,
                    "pred": float(r["pred_weekly"].sum()),
                    "pred_peak": float(r["pred_weekly"][is_peak].sum()),
                }
            )
            diag_records.append(
                {
                    "product_variant_id": pv,
                    "location_id": loc,
                    "cutoff": cutoff,
                    "aic": r["aic"],
                    "converged": r["converged"],
                    "fallback": r["fallback"],
                    "fit_error": r["error"],
                }
            )
        preds = pd.DataFrame(pred_records)
        diag_rows.append(pd.DataFrame(diag_records))

        actual_main = (
            panel[panel["period"].isin(horizon_periods)]
            .groupby(["product_variant_id", "location_id"], as_index=False)["qty_sold_net"]
            .sum()
            .rename(columns={"qty_sold_net": "actual"})
        )
        peak_periods = horizon_periods[is_peak]
        actual_peak = (
            panel[panel["period"].isin(peak_periods)]
            .groupby(["product_variant_id", "location_id"], as_index=False)["qty_sold_net"]
            .sum()
            .rename(columns={"qty_sold_net": "actual"})
        )

        main_window = preds[["product_variant_id", "location_id", "cutoff", "pred"]].merge(
            actual_main, on=["product_variant_id", "location_id"], how="left"
        )
        main_window["actual"] = main_window["actual"].fillna(0.0)
        peak_window = (
            preds[["product_variant_id", "location_id", "cutoff", "pred_peak"]]
            .rename(columns={"pred_peak": "pred"})
            .merge(actual_peak, on=["product_variant_id", "location_id"], how="left")
        )
        peak_window["actual"] = peak_window["actual"].fillna(0.0)

        main_rows.append(main_window)
        peak_rows.append(peak_window)

        # Final-cutoff-only model artifacts, exemplar entities only (see _select_exemplars).
        # Refit sequentially outside the parallel dispatch, since only 2-3 fitted objects
        # need to survive -- returning every one of 6,054 fitted objects through joblib's
        # IPC just to discard almost all of them would be wasteful.
        if cutoff == cutoffs[-1]:
            for label, key in EXEMPLAR_ENTITIES.items():
                if key not in entity_pos:
                    print(f"WARNING: exemplar entity {key} ({label}) not present at the final cutoff -- skipping artifact")
                    continue
                idx = entity_pos[key]
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    exemplar_model = SARIMAX(
                        y_matrix[idx],
                        exog=exog_train,
                        order=order,
                        seasonal_order=seasonal_order,
                        trend=trend,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                        simple_differencing=True,
                    )
                    exemplar_fits[label] = exemplar_model.fit(maxiter=MAXITER, disp=False)

    window_totals = pd.concat(main_rows, ignore_index=True)
    peak_window_totals = pd.concat(peak_rows, ignore_index=True)
    fit_diagnostics = pd.concat(diag_rows, ignore_index=True)

    results = evaluate(window_totals)
    peak_results = evaluate(peak_window_totals)

    # Post-hoc per-segment breakdown, same pattern as train_random_forest.py.
    per_series_by_segment = results["per_series"].merge(_segments, on=["product_variant_id", "location_id"], how="left")
    unmatched = int(per_series_by_segment["category"].isna().sum())
    if unmatched:
        print(f"WARNING: {unmatched}/{len(per_series_by_segment)} series had no demand_classification.csv match")
    segment_summary = per_series_by_segment.groupby("category")[["rmse", "bias"]].mean()

    return {
        "results": results,
        "peak_results": peak_results,
        "window_totals": window_totals,
        "peak_window_totals": peak_window_totals,
        "fit_diagnostics": fit_diagnostics,
        "segment_summary": segment_summary,
        "exemplar_fits": exemplar_fits,
    }


# %% [markdown]
# ## 5. MLflow logging


# %%
def log_run(
    order: tuple, seasonal_order: tuple, run_name: str, mlflow, data_version: dict, lib_versions: dict, trend: str = None
) -> None:
    outcome = run_walk_forward(order, seasonal_order, run_name, trend)
    results, peak_results = outcome["results"], outcome["peak_results"]
    diag = outcome["fit_diagnostics"]

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags(
            {
                "phase": "3_model_comparison",
                "task_ids": "3.5",
                "grain": "weekly (summed to 91d window)",
                "data_source": MARTS_SCRATCH,
                **{f"data_{k}": v for k, v in data_version.items()},
                **lib_versions,
            }
        )
        mlflow.log_params(
            {
                "order": str(order),
                "seasonal_order": str(seasonal_order),
                "sarimax_trend": trend or "none",
                "exog_cols": ",".join(MONTH_COLS),
                "maxiter": MAXITER,
                "n_jobs": -1,
                "horizon_weeks": HORIZON_WEEKS,
                "walk_forward_cutoffs": 4,
                "walk_forward_step_days": 91,
                "trend_handling": (
                    "d=0 seasonal-only differencing (D=1) + SARIMAX trend='c' to capture growth drift"
                    if trend
                    else "non-seasonal + seasonal differencing (d=1, D=1), no trend term"
                ),
                "sample_entities": SAMPLE_ENTITIES or "full_catalog",
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

        comparison = compare_to_baseline(results["portfolio"])
        mlflow.log_metric("beats_baseline_pct", 100 * comparison["beats_baseline"].mean())

        mlflow.log_metrics(
            {
                "pct_fit_failures": 100 * diag["fallback"].mean(),
                "pct_non_converged": 100 * (~diag["converged"]).mean(),
                "mean_aic": float(diag["aic"].mean(skipna=True)),
                "n_series_fallback_zero": int(diag["fallback"].sum()),
            }
        )

        # Final-cutoff models, exemplar entities only -- see _select_exemplars for why not
        # all 6,054 (impractical artifact bloat; per-series diagnostics are in fit_diagnostics.csv).
        for label, fitted_model in outcome["exemplar_fits"].items():
            mlflow.statsmodels.log_model(fitted_model, name=f"model_{label}")

        for name, df in (
            ("window_totals", outcome["window_totals"]),
            ("peak_window_totals", outcome["peak_window_totals"]),
            ("fit_diagnostics", outcome["fit_diagnostics"]),
            ("segment_summary", outcome["segment_summary"].reset_index()),
            ("compare_to_baseline", comparison),
        ):
            path = OUTPUT_DIR / f"{run_name}_{name}.csv"
            df.to_csv(path, index=False)
            mlflow.log_artifact(str(path))

        print(f"\n=== {run_name} ===")
        print(comparison.to_string(index=False))
        print(f"\nFit diagnostics: {100 * diag['fallback'].mean():.2f}% fallback, {100 * (~diag['converged']).mean():.2f}% non-converged")
        print("\nPer-segment RMSE/bias (post-hoc):")
        print(outcome["segment_summary"].to_string())


# %% [markdown]
# ## 6. Timed pilot -- run before committing to the full 24,216-fit run

# %%
def run_pilot(n_series: int, order: tuple = (1, 1, 1), seasonal_order: tuple = (0, 1, 0, SEASONAL_PERIOD)) -> None:
    import time

    cutoff = get_cutoffs()[0]
    train = panel[panel["period"] <= cutoff - STRADDLE_LAG]
    train_periods = pd.date_range(train["period"].min(), cutoff - STRADDLE_LAG, freq="W-MON")
    horizon_periods = pd.date_range(cutoff + pd.Timedelta(days=1), periods=HORIZON_WEEKS, freq="W-MON")
    exog_lookup = _calendar_lookup(train_periods.union(horizon_periods))
    exog_train = exog_lookup.loc[train_periods].to_numpy(dtype="float64")
    exog_future = exog_lookup.loc[horizon_periods].to_numpy(dtype="float64")

    wide = _pivot_qty(train, train_periods)
    sample = wide.sample(n=min(n_series, len(wide)), random_state=42)
    entities = sample.index.tolist()
    y_matrix = sample.to_numpy(dtype="float64")

    start = time.perf_counter()
    Parallel(n_jobs=-1)(  # default (loky/process) backend -- see run_walk_forward's comment on why
        delayed(fit_one_series)(entities[i], y_matrix[i], exog_train, exog_future, order, seasonal_order)
        for i in range(len(entities))
    )
    elapsed = time.perf_counter() - start

    total_catalog_entities = panel[["product_variant_id", "location_id"]].drop_duplicates().shape[0]
    total_fits = total_catalog_entities * len(get_cutoffs())
    per_fit = elapsed / len(entities)
    print(f"Pilot: {len(entities)} series, {elapsed:.1f}s total, {per_fit:.3f}s/fit")
    print(f"Full catalog: {total_catalog_entities} entities x {len(get_cutoffs())} cutoffs = {total_fits} fits")
    # per_fit already reflects n_jobs=-1 parallel throughput (this pilot used the same
    # Parallel(n_jobs=-1) dispatch the real run does), so this is a direct wall-clock
    # extrapolation, not a single-core figure needing further division by core count. If
    # anything it's conservative: each cutoff's real batch (6,054 tasks) amortizes
    # per-worker startup overhead better than this 100-task pilot does.
    print(f"Extrapolated full-run wall-clock (already reflects n_jobs=-1 parallelism): ~{per_fit * total_fits / 60:.1f} min")
    print("Use this estimate to decide whether to run the full RUNS loop.")


# %% [markdown]
# ## 7. Runs -- task 3.5 is a benchmark, not a tuning exercise, so this stays small
#
# Two configs, not a search: `--diagnose`'s ADF results (portfolio aggregate + 20 stratified
# per-series checks, all 20/20) show the log1p series are stationary around a trend, and
# diff(1)'s ACF shows the classic over-differencing signature. Growth handled by first
# differencing (`d=1`) and growth handled by `d=0` plus a trend term are therefore both run
# and logged, and the comparison against `seasonal_naive_genuine_91d_v2` decides between
# them -- see README.md for the reasoning and the result.

# %%
RUNS = {
    "sarima_baseline": dict(order=(1, 1, 1), seasonal_order=(0, 1, 0, SEASONAL_PERIOD), trend=None),
    "sarima_d0_trend": dict(order=(1, 0, 1), seasonal_order=(0, 1, 0, SEASONAL_PERIOD), trend="c"),
    # "sarima_seasonal_ar": dict(order=(1, 1, 1), seasonal_order=(1, 1, 0, SEASONAL_PERIOD), trend=None),  # enable
    # only if the timed pilot shows runtime headroom -- adding seasonal AR/MA terms multiplies
    # per-fit cost by the s=52 state dimension, see module docstring.
}

# %%
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run one or more of the RUNS configs; defaults to all.")
    parser.add_argument("run_names", nargs="*", choices=list(RUNS) or None, help="Subset of RUNS keys to execute.")
    parser.add_argument("--diagnose", action="store_true", help="Run order-selection diagnostics instead of fitting.")
    parser.add_argument("--pilot", type=int, default=0, metavar="N", help="Time a pilot of N random series at the first cutoff instead of a full run.")
    args = parser.parse_args()

    _setup(SAMPLE_ENTITIES)  # warehouse query + CSV read -- parent process only, see _setup()'s docstring

    if args.diagnose:
        diagnose_orders(panel, _segments)
        raise SystemExit(0)

    if args.pilot:
        run_pilot(args.pilot)
        raise SystemExit(0)

    selected = {name: RUNS[name] for name in (args.run_names or RUNS)}

    mlflow = init_mlflow_experiment(EXPERIMENT_PATH)
    data_version = get_table_version(MARTS_SCRATCH)
    lib_versions = get_library_versions(["statsmodels", "pandas", "numpy", "mlflow", "joblib"])
    print(f"Data snapshot: {data_version}")
    print(f"Library versions: {lib_versions}")
    print(f"Running: {list(selected)}")

    for run_name, cfg in selected.items():
        log_run(cfg["order"], cfg["seasonal_order"], run_name, mlflow, data_version, lib_versions, cfg.get("trend"))

    print(f"\n{list(selected)} logged under {EXPERIMENT_PATH}. See README.md for the results.")
