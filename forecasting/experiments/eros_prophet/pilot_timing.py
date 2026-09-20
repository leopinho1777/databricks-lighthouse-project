# %% [markdown]
# # Timing pilot — mandatory first step for task 3.4 (Prophet)
#
# Prophet fits ONE model PER (`product_variant_id`, `location_id`) series --
# unlike RF (task 3.2), which fit a single pooled model. With 6,054 series x 4
# rolling-origin cutoffs, that's up to 24,216 fits per run config, and 5
# exploratory configs are planned. That scale question can't be guessed at:
# this script times a stratified sample of real fits (the exact
# `RUNS["prophet_baseline"]` config from `train_prophet.py`, imported rather
# than duplicated so the two scripts can never silently drift) and
# extrapolates the real cost, mechanically deciding whether `train_prophet.py`
# runs against the full catalog or a fixed stratified subsample.
#
# `train_prophet.py`'s `load_run_scale()` hard-gates on this script's output
# (`output/timing_pilot_decision.csv`) — it raises rather than guessing if
# this hasn't run yet.

# %%
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from cmdstanpy.utils import get_logger as _get_cmdstanpy_logger
from prophet import Prophet

# See train_prophet.py's identical comment: plain logging.getLogger("cmdstanpy").setLevel(...)
# doesn't stick because cmdstanpy's own get_logger() clobbers the level on its first internal
# call. Force that init now via the same lru_cached get_logger(), then override the level.
_get_cmdstanpy_logger().setLevel(logging.ERROR)

FORECASTING = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FORECASTING / "experiments" / "_shared"))
from evaluate import get_cutoffs  # noqa: E402

sys.path.insert(0, str(FORECASTING / "10_feature_engineering" / "_shared"))
from panel_regression import load_weekly_panel  # noqa: E402

# Import the real baseline config from train_prophet.py, not a duplicated/stripped-down toy
# config -- the pilot must time the actual cost the real runs will pay, not an understatement.
sys.path.insert(0, str(Path(__file__).parent))
from train_prophet import MIN_TRAIN_POINTS, RUNS, STRADDLE_LAG  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

DEMAND_CLASSIFICATION_CSV = FORECASTING / "04_demand_classification" / "output" / "demand_classification.csv"

PILOT_SAMPLE_TARGET = 200  # ~3.3% of 6,054
PILOT_MIN_PER_CATEGORY = 15  # floor so the 193-row lumpy category isn't reduced to ~6 rows
PILOT_RANDOM_STATE = 42  # matches train_random_forest.py's seeding convention
HORIZON_WEEKS = 13

N_SERIES_FULL = 6054
N_CUTOFFS = 4
N_EXPLORATORY_RUNS = 5

# Threshold is a deliberately chosen per-fit budget (5400 / (6054*4) = 0.2235 s/fit), NOT derived
# from RF's ~10-minute single pooled fit -- RF's number is only a loose sanity anchor (one fit's
# model-complexity time on a fixed dataset), while Prophet's total cost here is dominated by
# cmdstanpy's fixed per-.fit() subprocess-spawn overhead (~0.3-1s) x series count, a completely
# different cost driver. If the pilot lands over this, that's an expected, acceptable outcome
# (subprocess-spawn overhead alone approaches this budget), not a failed pilot.
DECISION_THRESHOLD_SECONDS_PER_RUN_CONFIG = 90 * 60  # 5,400s = 90 minutes
DECISION_THRESHOLD_SECONDS_PER_FIT = DECISION_THRESHOLD_SECONDS_PER_RUN_CONFIG / (N_SERIES_FULL * N_CUTOFFS)  # ~0.2235


# %% [markdown]
# ## 1. Stratified sample, by demand_classification.csv category

# %%
def build_stratified_sample() -> pd.DataFrame:
    segments = pd.read_csv(DEMAND_CLASSIFICATION_CSV, usecols=["product_variant_id", "location_id", "category"])
    segments["product_variant_id"] = segments["product_variant_id"].astype(str)
    segments["location_id"] = segments["location_id"].astype(str)

    frac = PILOT_SAMPLE_TARGET / len(segments)
    parts = []
    for category, group in segments.groupby("category"):
        n = max(round(len(group) * frac), PILOT_MIN_PER_CATEGORY)
        n = min(n, len(group))
        parts.append(group.sample(n=n, random_state=PILOT_RANDOM_STATE))
    sample = pd.concat(parts, ignore_index=True)
    sample.to_csv(OUTPUT_DIR / "timing_pilot_sample_ids.csv", index=False)
    # Reused verbatim by train_prophet.py's stratified-subsample path -- never resampled
    # independently, so the pilot and the real runs are guaranteed to time/use the exact same series.
    return sample


# %% [markdown]
# ## 2. Time real fits on the sample, at the single most expensive cutoff

# %%
def time_prophet_fits(sample: pd.DataFrame, panel: pd.DataFrame, cutoff: pd.Timestamp, prophet_params: dict, use_holidays: bool) -> pd.DataFrame:
    train = panel[panel["period"] <= cutoff - STRADDLE_LAG]
    horizon_periods = pd.date_range(cutoff + pd.Timedelta(days=1), periods=HORIZON_WEEKS, freq="W-MON")
    # Grouped once, not re-filtered per series with a boolean mask -- see train_prophet.py's
    # run_walk_forward comment. The timed window below includes the per-series selection, so
    # the pilot measures the real per-iteration cost, not just Prophet's own fit+predict cost.
    grouped_train = train.groupby(["product_variant_id", "location_id"])

    timings = []
    warmed_up = False
    for pv_id, loc_id, category in sample.itertuples(index=False):
        # Timed from HERE, before series selection. get_group() is cheap after the one-time
        # groupby, but timing it keeps this pilot's number representative of "cost per real loop
        # iteration", not just "cost of Prophet itself".
        t0 = time.perf_counter()
        try:
            series_train = grouped_train.get_group((pv_id, loc_id))
        except KeyError:
            series_train = train.iloc[0:0]
        train_df = series_train.rename(columns={"period": "ds", "qty_sold_net": "y"})[["ds", "y"]].copy()
        train_df["y"] = np.log1p(train_df["y"])
        n_train_points = len(train_df)
        is_cold_start = n_train_points < MIN_TRAIN_POINTS

        if not warmed_up:
            # cmdstanpy pays a one-time backend-load cost on a process's first .fit() call that a
            # real 24,216-fit run amortizes to near-zero; a 208-fit pilot wouldn't. Exclude it
            # from the timed measurement (re-zero t0 after the warmup fit, below).
            if not is_cold_start:
                _warmup_model = Prophet(weekly_seasonality=False, yearly_seasonality=True, **prophet_params)
                if use_holidays:
                    _warmup_model.add_country_holidays(country_name="BR")
                try:
                    _warmup_model.fit(train_df)
                except Exception:
                    pass
                warmed_up = True
                t0 = time.perf_counter()  # re-zero: don't let the warm-up fit's cost leak into this series' own timing

        if is_cold_start:
            elapsed = None  # not fit -- cold-start fallback, doesn't contribute to the fit-time estimate
        else:
            try:
                model = Prophet(weekly_seasonality=False, yearly_seasonality=True, **prophet_params)
                if use_holidays:
                    model.add_country_holidays(country_name="BR")
                model.fit(train_df)
                model.predict(pd.DataFrame({"ds": horizon_periods}))
                elapsed = time.perf_counter() - t0
            except Exception:
                elapsed = None

        timings.append(
            {
                "product_variant_id": pv_id,
                "location_id": loc_id,
                "category": category,
                "n_train_points": n_train_points,
                "is_cold_start": is_cold_start,
                "elapsed_seconds": elapsed,
            }
        )

    return pd.DataFrame(timings)


# %% [markdown]
# ## 3. Extrapolate + decide

# %%
if __name__ == "__main__":
    panel = load_weekly_panel()
    pilot_cutoff = get_cutoffs()[-1]  # last cutoff = largest training window = most expensive
    baseline_cfg = RUNS["prophet_baseline"]

    sample = build_stratified_sample()
    print(f"Pilot sample: {len(sample)} series ({sample['category'].value_counts().to_dict()})")
    print(f"Pilot cutoff: {pilot_cutoff.date()}")

    timings = time_prophet_fits(sample, panel, pilot_cutoff, baseline_cfg["params"], baseline_cfg["use_holidays"])
    timings.to_csv(OUTPUT_DIR / "timing_pilot_results.csv", index=False)

    n_cold_start = int(timings["is_cold_start"].sum())
    n_errored = int(timings["elapsed_seconds"].isna().sum()) - n_cold_start  # fit attempted but raised
    n_timed = int(timings["elapsed_seconds"].notna().sum())

    print(f"\nCold-start fallbacks (fewer than {MIN_TRAIN_POINTS} training weeks): {n_cold_start}/{len(timings)}")
    if n_errored:
        print(f"WARNING: {n_errored} series attempted a real fit but raised an exception (not cold-start) -- investigate before trusting the extrapolation.")

    # Escape hatch: if the pilot itself didn't complete cleanly, stop and report rather than
    # extrapolate from partial/anomalous data. cmdstanpy is a brand-new dependency with a one-time
    # Windows compiler-toolchain setup, and RF's own session hit 3 unexpected runtime issues from
    # this dependency stack -- an unclean pilot run is a signal to investigate the environment, not
    # a data point to extrapolate from.
    if n_timed == 0:
        raise RuntimeError(
            "Pilot produced zero successful timed fits (all cold-start or errored) -- cannot "
            "extrapolate. Investigate the cmdstanpy/prophet install and MIN_TRAIN_POINTS before "
            "re-running."
        )
    if n_errored > 0.1 * len(timings):
        raise RuntimeError(
            f"{n_errored}/{len(timings)} series ({100 * n_errored / len(timings):.1f}%) raised "
            "exceptions during a real fit attempt (not cold-start fallback) -- this is not a clean "
            "pilot run. Stop and investigate before trusting an extrapolation from the remaining "
            "successful fits."
        )

    mean_fit_seconds = timings["elapsed_seconds"].mean()
    median_fit_seconds = timings["elapsed_seconds"].median()
    max_fit_seconds = timings["elapsed_seconds"].max()

    extrapolated_one_run_config_seconds = mean_fit_seconds * N_SERIES_FULL * N_CUTOFFS
    extrapolated_5_run_session_seconds = extrapolated_one_run_config_seconds * N_EXPLORATORY_RUNS

    decision = "full_catalog" if extrapolated_one_run_config_seconds <= DECISION_THRESHOLD_SECONDS_PER_RUN_CONFIG else "stratified_subsample"

    # Lumpy-segment stability: the floor sampling gives 15/193 lumpy series (7.8%, thinner than
    # intermittent's ~3.3% rate), and lumpy is the highest-variance category by definition -- this
    # isn't used to gate the scale decision, but is reported so a later "config X won" verdict from
    # subsample runs can be checked against segment stability, not just a portfolio mean.
    lumpy_timings = timings[(timings["category"] == "lumpy") & timings["elapsed_seconds"].notna()]
    lumpy_fit_seconds_std = float(lumpy_timings["elapsed_seconds"].std()) if len(lumpy_timings) > 1 else float("nan")

    decision_row = pd.DataFrame(
        [
            {
                "mean_fit_seconds": mean_fit_seconds,
                "median_fit_seconds": median_fit_seconds,
                "max_fit_seconds": max_fit_seconds,
                "n_pilot_series": len(sample),
                "n_timed": n_timed,
                "n_cold_start": n_cold_start,
                "n_errored": n_errored,
                "lumpy_fit_seconds_std": lumpy_fit_seconds_std,
                "extrapolated_one_run_config_seconds": extrapolated_one_run_config_seconds,
                "extrapolated_one_run_config_hours": extrapolated_one_run_config_seconds / 3600,
                "extrapolated_5_run_session_hours": extrapolated_5_run_session_seconds / 3600,
                "threshold_seconds_per_run_config": DECISION_THRESHOLD_SECONDS_PER_RUN_CONFIG,
                "threshold_seconds_per_fit": DECISION_THRESHOLD_SECONDS_PER_FIT,
                "pilot_cutoff": pilot_cutoff.date().isoformat(),
                "decision": decision,
            }
        ]
    )
    decision_row.to_csv(OUTPUT_DIR / "timing_pilot_decision.csv", index=False)

    print(f"\nMean fit+predict time: {mean_fit_seconds:.3f}s (median {median_fit_seconds:.3f}s, max {max_fit_seconds:.3f}s), n={n_timed}")
    print(f"Threshold: {DECISION_THRESHOLD_SECONDS_PER_FIT:.4f}s/fit ({DECISION_THRESHOLD_SECONDS_PER_RUN_CONFIG / 60:.0f} min/run-config)")
    print(f"Extrapolated one run config (6,054 series x 4 cutoffs): {extrapolated_one_run_config_seconds / 3600:.2f} hours")
    print(f"Extrapolated full 5-run exploratory session at this scale: {extrapolated_5_run_session_seconds / 3600:.2f} hours")
    print(f"Lumpy-segment fit-time std (stability check, informational): {lumpy_fit_seconds_std:.3f}s")
    print(f"\nDECISION: {decision}")
    if decision == "stratified_subsample":
        print(
            f"train_prophet.py will use the fixed {len(sample)}-series sample "
            "(timing_pilot_sample_ids.csv) for the 5 exploratory runs, then one full-catalog run "
            "for the winning config via --full-catalog."
        )
    else:
        print("train_prophet.py will use the full 6,054-series catalog for every run.")
