# %% [markdown]
# # Task 3.4 — Prophet on the frozen Stage 2 feature set
#
# One Prophet model PER (`product_variant_id`, `location_id`) series -- unlike
# RF (task 3.2), which fit a single pooled model across the whole catalog,
# Prophet only works one time series at a time. With 6,054 series x 4
# rolling-origin cutoffs, that's up to 24,216 individual fits per run config --
# a fundamentally different cost shape than RF's. `pilot_timing.py` MUST run
# first and decide (empirically, not by assumption) whether these runs use the
# full catalog or a fixed stratified subsample -- see `load_run_scale()` below,
# which refuses to guess.
#
# Scored against the Stage 3 protocol (`experiments/_shared/evaluate.py`):
# refit per rolling-origin cutoff, sum weekly predictions into a 91-day window
# total per series, compare against the `seasonal_naive_genuine_91d_v2`
# champion. Frozen feature set only (`10_frozen_feature_set.md`): calendar
# (here, Prophet's own yearly seasonality + BR holidays) + trend (here,
# Prophet's own changepoint-driven trend component) -- no other inputs.

# %%
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from cmdstanpy.utils import get_logger as _get_cmdstanpy_logger
from prophet import Prophet

# cmdstanpy logs "Chain [1] start/done processing" per .fit() call -- across up to 24,216
# fits that makes stdout unusable. `logging.getLogger("cmdstanpy").setLevel(...)` alone does
# NOT work here: cmdstanpy's own get_logger() lazily creates its handler on first use and
# unconditionally resets the logger's level to DEBUG at that point (see
# cmdstanpy/utils/logging.py), clobbering any level set before cmdstanpy's first internal
# call. Calling get_logger() ourselves forces that lazy init now (it's lru_cached, so
# cmdstanpy's later internal calls reuse this same instance), then we override the level.
_get_cmdstanpy_logger().setLevel(logging.ERROR)

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

HORIZON_WEEKS = 13  # 91 days
STRADDLE_LAG = pd.Timedelta(days=6)  # IDENTICAL to train_random_forest.py's straddle-week logic --
# reused, not redesigned. The protocol's 4 cutoffs are all Tuesdays (91 = 13*7, weekday never
# shifts), so no week's Monday-anchor lines up with a cutoff exactly. Excluded from both train
# (period <= cutoff - 6 days) and the scored horizon (starts first Monday strictly after cutoff).
TRAIN_END = pd.Timestamp("2024-12-31")  # matches RF's / run_genuine_baseline.py's peak-month reference

MIN_TRAIN_POINTS = 10  # ~2.5 months of weekly history. Below this, or on any other per-series fit
# failure, fall back to a zero forecast rather than crash the loop -- same "no training history ->
# forecast 0" convention train_random_forest.py documents for genuinely new entities, applied here
# per-series. This threshold is NOT derived from this catalog's actual history depths; pilot_timing.py
# reports the cold-start fallback rate on its own sample so this can be sanity-checked before the
# full run inherits it (see notes.md).

PILOT_DECISION_CSV = OUTPUT_DIR / "timing_pilot_decision.csv"
PILOT_SAMPLE_CSV = OUTPUT_DIR / "timing_pilot_sample_ids.csv"

# %% [markdown]
# ## 1. Load the weekly panel once; everything below is derived per-cutoff from it.

# %%
panel = load_weekly_panel()  # period (Monday-anchored weekly Timestamp), product_variant_id (str), location_id (str), qty_sold_net (float)

_segments = pd.read_csv(DEMAND_CLASSIFICATION_CSV, usecols=["product_variant_id", "location_id", "category"])
_segments["product_variant_id"] = _segments["product_variant_id"].astype(str)
_segments["location_id"] = _segments["location_id"].astype(str)

# Peak months: computed ONCE, from data up to the fixed TRAIN_END only -- matching
# train_random_forest.py's / run_genuine_baseline.py's approach (a single value reused across all
# 4 cutoffs), so this run's peak-season slice stays defined the same way as the champion baseline's.
_train_end_data = panel[panel["period"] <= TRAIN_END - STRADDLE_LAG]
_monthly = _train_end_data.groupby([_train_end_data["period"].dt.year, _train_end_data["period"].dt.month])["qty_sold_net"].sum()
_avg_by_month = _monthly.groupby(level=1).mean()
PEAK_MONTHS = sorted(_avg_by_month[_avg_by_month > _avg_by_month.mean()].index.tolist())
print(f"Peak-season months (from data <= {TRAIN_END.date()}): {PEAK_MONTHS}")

# Exemplar series for the mandated "trend/seasonality decomposition" plot deliverable: the single
# highest-volume (product_variant_id, location_id) pair, computed once from the full training
# window as of the LAST (largest) cutoff -- deterministic and reproducible regardless of which
# run-scale the pilot decides. Always fit and plotted even under the stratified-subsample scale
# (see run_walk_forward below, which adds it into `pairs` if not already sampled).
_LAST_CUTOFF = get_cutoffs()[-1]
_train_for_exemplar = panel[panel["period"] <= _LAST_CUTOFF - STRADDLE_LAG]
_totals = _train_for_exemplar.groupby(["product_variant_id", "location_id"])["qty_sold_net"].sum().sort_values(ascending=False)
EXEMPLAR_SERIES = _totals.index[0]  # (product_variant_id, location_id) tuple
EXEMPLAR_VOLUME = float(_totals.iloc[0])  # total training-period qty_sold_net, for notes.md/output
print(f"Exemplar series for decomposition plot: product_variant_id={EXEMPLAR_SERIES[0]}, "
      f"location_id={EXEMPLAR_SERIES[1]}, training-period volume={EXEMPLAR_VOLUME:.1f}")


# %% [markdown]
# ## 2. Per-series fit/forecast helper (cold-start-safe)

# %%
def fit_and_forecast_one_series(
    train_df: pd.DataFrame, horizon_periods: pd.DatetimeIndex, prophet_params: dict, use_holidays: bool
) -> tuple[np.ndarray, "Prophet | None"]:
    """Returns (pred_qty, fitted_model_or_None).

    Cold-start / short-history handling: Prophet cannot fit on fewer than 2 rows and produces
    unstable yearly-seasonality/changepoint estimates well above that floor. MIN_TRAIN_POINTS=10
    is the threshold below which this returns a zero-forecast fallback instead of attempting a
    fit. Any other Prophet-internal fit failure (e.g. numerical issues on a degenerate series) is
    also caught and treated as the same fallback, so a single pathological series can never crash
    a 6,054-series x 4-cutoff loop.
    """
    if len(train_df) < MIN_TRAIN_POINTS:
        return np.zeros(len(horizon_periods)), None

    model = Prophet(weekly_seasonality=False, yearly_seasonality=True, **prophet_params)
    # weekly_seasonality=False: the panel is already weekly-aggregated (load_weekly_panel), so
    # there is no sub-weekly cycle left for Prophet to model. yearly_seasonality=True (not "auto"):
    # "auto" silently disables yearly seasonality below ~2 full cycles of history, and per-series
    # history length varies a lot across this catalog -- explicit True makes every fitted series
    # actually attempt seasonality rather than silently degrading to trend-only without recording it.
    if use_holidays:
        model.add_country_holidays(country_name="BR")
    try:
        model.fit(train_df)
    except Exception:
        return np.zeros(len(horizon_periods)), None

    future = pd.DataFrame({"ds": horizon_periods})
    forecast = model.predict(future)
    # forecast["yhat"] is a pandas Series (model.predict() returns a DataFrame, unlike
    # sklearn's model.predict() which returns a bare ndarray) -- np.expm1() on a Series stays
    # a Series, so pandas' .clip(lower=...) is needed here, not numpy's .clip(min=...)
    # train_random_forest.py needed (the exact opposite mistake: that script's model.predict()
    # returns an ndarray, so pandas' lower= there raised instead).
    pred = np.expm1(forecast["yhat"]).clip(lower=0).to_numpy()
    return pred, model


# %% [markdown]
# ## 3. Walk-forward loop

# %%
def run_walk_forward(prophet_params: dict, use_holidays: bool, series_ids: pd.DataFrame | None) -> dict:
    main_rows, peak_rows = [], []
    cold_start_counts = {}
    n_series_fit = 0
    exemplar_plot_fig = None
    exemplar_model_final = None
    t_start = time.perf_counter()

    for cutoff in get_cutoffs():
        train = panel[panel["period"] <= cutoff - STRADDLE_LAG]
        pairs = train[["product_variant_id", "location_id"]].drop_duplicates()

        if series_ids is not None:
            pairs = pairs.merge(series_ids[["product_variant_id", "location_id"]], on=["product_variant_id", "location_id"])
            # The exemplar series is ALWAYS included even under the subsample scale -- the
            # decomposition-plot deliverable must not depend on which run-scale the pilot chose.
            has_exemplar = ((pairs["product_variant_id"] == EXEMPLAR_SERIES[0]) & (pairs["location_id"] == EXEMPLAR_SERIES[1])).any()
            if not has_exemplar:
                pairs = pd.concat(
                    [pairs, pd.DataFrame([{"product_variant_id": EXEMPLAR_SERIES[0], "location_id": EXEMPLAR_SERIES[1]}])],
                    ignore_index=True,
                )
        n_series_fit = len(pairs)

        horizon_periods = pd.date_range(cutoff + pd.Timedelta(days=1), periods=HORIZON_WEEKS, freq="W-MON")
        cold_starts_this_cutoff = 0
        rows = []

        # Grouped ONCE per cutoff, then looked up per series via get_group() -- NOT re-filtered
        # with a fresh boolean mask over the full (~2.1M-row) `train` frame inside the loop. A
        # naive `train[(train["product_variant_id"] == pv_id) & (train["location_id"] == loc_id)]`
        # per series is an O(panel_rows) scan repeated 6,054 times per cutoff (24,216 times total)
        # -- measured to cost ~92 of a real run's 155.8 minutes (a first live run came in at
        # ~2.45x the timing pilot's extrapolation before this fix; see notes.md's "Pilot
        # extrapolation was wrong" section). Grouping once is O(panel_rows) total, then each
        # lookup is cheap.
        grouped_train = train.groupby(["product_variant_id", "location_id"])

        for pv_id, loc_id in pairs.itertuples(index=False):
            try:
                series_train = grouped_train.get_group((pv_id, loc_id))
            except KeyError:
                series_train = train.iloc[0:0]  # no training history for this pair at this cutoff -- cold-start fallback
            train_df = series_train.rename(columns={"period": "ds", "qty_sold_net": "y"})[["ds", "y"]].copy()
            train_df["y"] = np.log1p(train_df["y"])

            pred, model = fit_and_forecast_one_series(train_df, horizon_periods, prophet_params, use_holidays)
            if model is None:
                cold_starts_this_cutoff += 1

            if (pv_id, loc_id) == EXEMPLAR_SERIES and cutoff == _LAST_CUTOFF and model is not None:
                # Decomposition plot needs history + horizon in one forecast frame, not just the
                # horizon -- otherwise plot_components() only shows 13 weeks of trend, not a
                # meaningful decomposition.
                full_plot_df = pd.concat([train_df[["ds"]], pd.DataFrame({"ds": horizon_periods})], ignore_index=True)
                full_forecast = model.predict(full_plot_df)
                exemplar_plot_fig = model.plot_components(full_forecast)
                exemplar_model_final = model

            rows.append(pd.DataFrame({"product_variant_id": pv_id, "location_id": loc_id, "period": horizon_periods, "qty_pred": pred}))

        cold_start_counts[cutoff] = cold_starts_this_cutoff
        future = pd.concat(rows, ignore_index=True)

        # `actual` isn't restricted to `pairs` -- a genuinely new entity appearing only after the
        # cutoff has no row in `future`, so qty_pred is NaN after the merge; `.sum(skipna=True)`
        # reduces an all-NaN entity-window to a predicted total of 0, same convention as
        # train_random_forest.py.
        actual = panel[panel["period"].isin(horizon_periods)]
        weekly = actual.merge(future, on=["product_variant_id", "location_id", "period"], how="left")
        weekly["is_peak"] = weekly["period"].dt.month.isin(PEAK_MONTHS)

        def _window_totals(g: pd.DataFrame) -> pd.DataFrame:
            out = g.groupby(["product_variant_id", "location_id"], as_index=False).agg(actual=("qty_sold_net", "sum"), pred=("qty_pred", "sum"))
            out["cutoff"] = cutoff
            return out

        main_rows.append(_window_totals(weekly))
        peak_rows.append(_window_totals(weekly[weekly["is_peak"]]))

    window_totals = pd.concat(main_rows, ignore_index=True)
    peak_window_totals = pd.concat(peak_rows, ignore_index=True)
    results = evaluate(window_totals)
    peak_results = evaluate(peak_window_totals)

    per_series_by_segment = results["per_series"].merge(_segments, on=["product_variant_id", "location_id"], how="left")
    unmatched = int(per_series_by_segment["category"].isna().sum())
    if unmatched:
        print(f"WARNING: {unmatched}/{len(per_series_by_segment)} series had no demand_classification.csv match")
    segment_summary = per_series_by_segment.groupby("category")[["rmse", "bias"]].agg(["mean", "std", "min", "max"])
    # Lumpy-segment stability check: the pilot's stratified sample floors lumpy at 15/193 series
    # (7.8%, thinner than intermittent's ~3.3% rate) and lumpy is the highest-variance category by
    # definition -- report spread (std/min/max), not just mean, so a "config X won" verdict from a
    # subsample run is checked against whether it's a stable segment result before being carried
    # into the single full-catalog final run.

    return {
        "results": results,
        "peak_results": peak_results,
        "window_totals": window_totals,
        "peak_window_totals": peak_window_totals,
        "segment_summary": segment_summary,
        "cold_start_counts": cold_start_counts,
        "n_series_fit": n_series_fit,
        "exemplar_plot_fig": exemplar_plot_fig,
        "exemplar_model_final": exemplar_model_final,
        "wall_clock_seconds": time.perf_counter() - t_start,
    }


# %% [markdown]
# ## 4. Run-scale gate -- reads pilot_timing.py's decision, refuses to guess

# %%
def load_run_scale() -> tuple[str, pd.DataFrame | None]:
    """Reads pilot_timing.py's decision. Refuses to guess a scale -- if the pilot hasn't
    been run, this raises rather than silently defaulting to full-catalog (which could hang
    for hours) or to a subsample (which would silently under-scope the deliverable)."""
    if not PILOT_DECISION_CSV.exists():
        raise FileNotFoundError(
            "timing_pilot_decision.csv not found -- run `python pilot_timing.py` first. "
            "The run-scale (full catalog vs. stratified subsample) is an empirical decision, "
            "not a default; see forecasting/experiments/eros_prophet/notes.md."
        )
    decision_row = pd.read_csv(PILOT_DECISION_CSV).iloc[0]
    decision = decision_row["decision"]
    sample = pd.read_csv(PILOT_SAMPLE_CSV, dtype=str) if decision == "stratified_subsample" else None
    return decision, sample


# %% [markdown]
# ## 5. MLflow logging
#
# Manual logging only (no autolog): each run refits up to 24,216 models inside one
# `mlflow.start_run()`. Only ONE model and ONE plot are ever logged as artifacts -- the exemplar
# series' final-cutoff fit -- never one artifact per series (infeasible at 6,054 series). This
# scopes train_random_forest.py's own "final-cutoff model only, not all 4 folds" reasoning down
# one further level (per-series, not just per-fold).

# %%
def log_run(prophet_params: dict, run_name: str, use_holidays: bool, mlflow, data_version: dict, lib_versions: dict, run_scale: str, series_ids) -> None:
    outcome = run_walk_forward(prophet_params, use_holidays, series_ids)
    results, peak_results = outcome["results"], outcome["peak_results"]

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags(
            {
                "phase": "3_model_comparison",
                "task_ids": "3.4",
                "grain": "weekly (summed to 91d window); one Prophet fit per (product_variant_id, location_id) series",
                "data_source": MARTS_SCRATCH,
                "run_scale": run_scale,  # "full_catalog" | "stratified_subsample"
                **{f"data_{k}": v for k, v in data_version.items()},
                **lib_versions,
            }
        )
        mlflow.log_params(
            {
                **prophet_params,
                "use_country_holidays_BR": use_holidays,
                "weekly_seasonality": False,
                "yearly_seasonality": True,
                "horizon_weeks": HORIZON_WEEKS,
                "walk_forward_cutoffs": 4,
                "target_transform": "log1p",
                "min_train_points": MIN_TRAIN_POINTS,
                "n_series_fit": outcome["n_series_fit"],
                "exemplar_series_product_variant_id": EXEMPLAR_SERIES[0],
                "exemplar_series_location_id": EXEMPLAR_SERIES[1],
                "exemplar_series_training_volume": EXEMPLAR_VOLUME,
            }
        )

        for _, row in results["portfolio"].iterrows():
            cutoff_str = row["cutoff"].date().isoformat()
            mlflow.log_metric(f"wape_pct_{cutoff_str}", row["wape_pct"])
            mlflow.log_metric(f"actual_total_{cutoff_str}", row["actual_total"])
            mlflow.log_metric(f"bias_{cutoff_str}", row["bias"])
            mlflow.log_metric(f"cold_start_fallback_count_{cutoff_str}", outcome["cold_start_counts"][row["cutoff"]])

        summary = results["per_series_summary"].iloc[0]
        mlflow.log_metrics({"rmse_mean": summary["rmse_mean"], "rmse_median": summary["rmse_median"], "bias_mean": summary["bias_mean"]})
        peak_summary = peak_results["per_series_summary"].iloc[0]
        mlflow.log_metrics({"peak_rmse_mean": peak_summary["rmse_mean"], "peak_rmse_median": peak_summary["rmse_median"], "peak_bias_mean": peak_summary["bias_mean"]})

        comparison = compare_to_baseline(results["portfolio"])
        mlflow.log_metric("beats_baseline_pct", 100 * comparison["beats_baseline"].mean())
        mlflow.log_metric("wall_clock_seconds", outcome["wall_clock_seconds"])

        segment_flat = outcome["segment_summary"].copy()
        segment_flat.columns = ["_".join(c) for c in segment_flat.columns]
        segment_flat = segment_flat.reset_index()
        if "lumpy" in segment_flat["category"].values:
            lumpy_row = segment_flat[segment_flat["category"] == "lumpy"].iloc[0]
            mlflow.log_metric("lumpy_rmse_std", lumpy_row["rmse_std"])
            mlflow.log_metric("lumpy_bias_std", lumpy_row["bias_std"])

        # Only ONE model, for ONE series -- see module docstring §5.
        if outcome["exemplar_model_final"] is not None:
            try:
                import mlflow.prophet

                mlflow.prophet.log_model(outcome["exemplar_model_final"], name="exemplar_model")
            except Exception as exc:
                # mlflow-skinny (this project's dependency, not full mlflow) already caused 2
                # missing-optional-dependency surprises for RF (skops, mlflow.__version__ lookup) --
                # fall back to Prophet's own JSON serialization as a plain artifact rather than
                # blocking the whole run on an mlflow-flavor packaging issue.
                print(f"mlflow.prophet.log_model failed ({exc}); falling back to prophet's own model_to_json()")
                from prophet.serialize import model_to_json

                model_json_path = OUTPUT_DIR / f"{run_name}_exemplar_model.json"
                model_json_path.write_text(model_to_json(outcome["exemplar_model_final"]))
                mlflow.log_artifact(str(model_json_path))

        if outcome["exemplar_plot_fig"] is not None:
            plot_path = OUTPUT_DIR / f"{run_name}_exemplar_decomposition.png"
            outcome["exemplar_plot_fig"].savefig(plot_path)
            mlflow.log_artifact(str(plot_path))

        for name, df in (
            ("window_totals", outcome["window_totals"]),
            ("peak_window_totals", outcome["peak_window_totals"]),
            ("segment_summary", segment_flat),
            ("compare_to_baseline", comparison),
        ):
            path = OUTPUT_DIR / f"{run_name}_{name}.csv"
            df.to_csv(path, index=False)
            mlflow.log_artifact(str(path))

        print(f"\n=== {run_name} ({run_scale}, {outcome['n_series_fit']} series, {outcome['wall_clock_seconds']/60:.1f} min) ===")
        print(comparison.to_string(index=False))
        print("\nPer-segment RMSE/bias/std (post-hoc diagnostic):")
        print(segment_flat.to_string(index=False))
        print(f"\nCold-start fallback counts per cutoff: {outcome['cold_start_counts']}")


# %% [markdown]
# ## 6. Runs -- default config first, then one hyperparameter category at a time

# %%
RUNS = {
    # Prophet's own library defaults -- the mandatory reference point every subsequent variation
    # is measured against.
    "prophet_baseline": dict(params=dict(changepoint_prior_scale=0.05, seasonality_mode="additive"), use_holidays=True),
    # 10_frozen_feature_set.md explicitly flags that Prophet's default changepoint settings need
    # checking against this project's confirmed ~14-17%/year smooth growth -- flexible/rigid
    # variants are the two directions to check.
    "prophet_changepoint_flexible": dict(params=dict(changepoint_prior_scale=0.5, seasonality_mode="additive"), use_holidays=True),
    "prophet_changepoint_rigid": dict(params=dict(changepoint_prior_scale=0.01, seasonality_mode="additive"), use_holidays=True),
    # Seasonality-mode ablation: the target is already log1p(qty_sold_net), which linearizes
    # multiplicative seasonal effects in log-space -- a small/no difference here is an expected,
    # not surprising, result worth confirming rather than assumed.
    "prophet_seasonality_multiplicative": dict(params=dict(changepoint_prior_scale=0.05, seasonality_mode="multiplicative"), use_holidays=True),
    # Ablation testing the task's own stated justification directly ("purpose-built for seasonal,
    # holiday-driven time series"): 10_frozen_feature_set.md already found holidays contributed
    # ~0% in a pooled linear panel regression -- this is Prophet's independent per-series test of
    # the same question, not assumed to replicate that finding.
    "prophet_no_holidays": dict(params=dict(changepoint_prior_scale=0.05, seasonality_mode="additive"), use_holidays=False),
}

# %%
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run one or more of the RUNS configs; defaults to all.")
    parser.add_argument("run_names", nargs="*", choices=list(RUNS) or None, help="Subset of RUNS keys to execute.")
    parser.add_argument(
        "--full-catalog",
        metavar="RUN_NAME",
        choices=list(RUNS),
        help="Force the full 6,054-series catalog for exactly this one named config, bypassing the "
        "pilot's stratified-subsample decision. Use this once, for the winning config, after the "
        "5 exploratory subsample runs -- that run is the tracker's actual 3.4 deliverable.",
    )
    args = parser.parse_args()

    run_scale, subsample_ids = load_run_scale()  # raises with a clear message if pilot_timing.py hasn't run
    print(f"Run scale (from timing pilot): {run_scale}")

    mlflow = init_mlflow_experiment(EXPERIMENT_PATH)
    data_version = get_table_version(MARTS_SCRATCH)
    lib_versions = get_library_versions(["prophet", "cmdstanpy", "pandas", "numpy", "mlflow"])
    print(f"Data snapshot: {data_version}\nLibrary versions: {lib_versions}")

    if args.full_catalog:
        cfg = RUNS[args.full_catalog]
        run_name = f"{args.full_catalog}_full_catalog_final"
        print(f"Running {run_name} at full catalog scale (6,054 series)...")
        log_run(cfg["params"], run_name, cfg["use_holidays"], mlflow, data_version, lib_versions, "full_catalog", None)
        print(f"\n{run_name} logged under {EXPERIMENT_PATH}. See notes.md for the running log.")
    else:
        selected = {name: RUNS[name] for name in (args.run_names or RUNS)}
        if run_scale == "stratified_subsample":
            print(f"Using fixed {len(subsample_ids)}-series subsample from timing_pilot_sample_ids.csv for all exploratory runs.")
        print(f"Running: {list(selected)}")

        for run_name, cfg in selected.items():
            log_run(cfg["params"], run_name, cfg["use_holidays"], mlflow, data_version, lib_versions, run_scale, subsample_ids)

        if run_scale == "stratified_subsample":
            print(
                "\nNOTE: the runs above used a stratified subsample, per the timing pilot's decision. "
                "Once the best config is picked, run it once more against the full catalog:\n"
                "    python train_prophet.py --full-catalog <best_run_name>\n"
                "That run becomes the tracker's actual 3.4 MLflow-run deliverable."
            )
        print(f"\n{list(selected)} logged under {EXPERIMENT_PATH}. See notes.md for the running log.")
