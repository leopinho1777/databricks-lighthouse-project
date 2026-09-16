# %% [markdown]
# # Task 2.4 -- Add weather features
#
# Builds on task 2.3's `baseline+calendar+holidays` formula. Weather data
# doesn't exist anywhere in this project (confirmed by exploration before
# this stage started) -- sourced from Open-Meteo's free historical archive
# API (no key required), joined via a small state-capital coordinate lookup
# since `dim_locations`' city names are fictional mock data (see
# `state_capital_coordinates.py`).
#
# `baseline+calendar+holidays` is refit here in-memory purely to compute this
# task's delta -- not re-logged (task 2.3 already logged it). Only
# `baseline+calendar+holidays+weather` is logged as a new MLflow run.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_holidays"))

import pandas as pd
import requests
from add_calendar_features import add_calendar_features
from add_holiday_features import add_holiday_features
from state_capital_coordinates import STATE_CAPITAL_COORDINATES

from _shared.panel_regression import fit_and_evaluate, init_mlflow_experiment, load_weekly_panel, query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MAPE_IMPROVEMENT_THRESHOLD = 0.02
WEATHER_START_DATE = "2019-12-30"  # covers the first ISO week in the panel
WEATHER_END_DATE = "2025-12-31"  # panel data past the 2025 holdout year is never used by fit_and_evaluate

# %% [markdown]
# ## 1. Location -> state -> weather join
#
# `dim_locations` is queried live (not hardcoded) so this stays correct if
# the location list ever changes; only the 4 distinct states actually present
# get a weather API call each, cached to `output/_weather_daily.parquet`.


# %%
def fetch_daily_weather(state_code: str, lat: float, lon: float) -> pd.DataFrame:
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": WEATHER_START_DATE,
            "end_date": WEATHER_END_DATE,
            "daily": "temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
            "timezone": "America/Sao_Paulo",
        },
        timeout=60,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    df = pd.DataFrame(daily)
    df["state_code"] = state_code
    return df


def load_weather_by_location() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_weather_daily.parquet"
    if cache_path.exists():
        weather_daily = pd.read_parquet(cache_path)
    else:
        frames = []
        for state_code, coords in STATE_CAPITAL_COORDINATES.items():
            frames.append(fetch_daily_weather(state_code, coords["lat"], coords["lon"]))
            time.sleep(1)  # be polite to the free, unauthenticated API
        weather_daily = pd.concat(frames, ignore_index=True)
        weather_daily.to_parquet(cache_path)

    weather_daily["date"] = pd.to_datetime(weather_daily["time"])
    weather_daily["week_start"] = weather_daily["date"] - pd.to_timedelta(weather_daily["date"].dt.weekday, unit="D")
    weekly_weather = (
        weather_daily.groupby(["state_code", "week_start"])
        .agg(
            temp_mean=("temperature_2m_mean", "mean"),
            precip_sum=("precipitation_sum", "sum"),
            wind_max=("wind_speed_10m_max", "max"),
        )
        .reset_index()
    )

    locations = query_df(
        "select location_id, state_code from develop.eros_analytics_marts.dim_locations"
    )
    locations["location_id"] = locations["location_id"].astype(str)

    return locations.merge(weekly_weather, on="state_code", how="left")


# %% [markdown]
# ## 2. Join onto the panel


# %%
def add_weather_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    weather_by_location = load_weather_by_location()
    df = df.merge(
        weather_by_location[["location_id", "week_start", "temp_mean", "precip_sum", "wind_max"]],
        left_on=["location_id", "period"],
        right_on=["location_id", "week_start"],
        how="left",
    ).drop(columns=["week_start"])
    feature_cols = ["temp_mean", "precip_sum", "wind_max"]
    missing = df[feature_cols].isna().any(axis=1).sum()
    if missing:
        raise ValueError(f"{missing} panel rows have no matching weather data -- check date range/state coverage")
    return df, feature_cols


# %% [markdown]
# ## 3. MLflow logging (new run only)


# %%
def log_run(mlflow, run: dict, feature_cols: list[str], cumulative_features: str):
    with mlflow.start_run(run_name=run["run_name"]) as mlflow_run:
        mlflow.set_tags(
            {
                "phase": "2_feature_engineering",
                "task_ids": "2.4",
                "grain": "product_variant_id x location_id (SKU x Store) x ISO week",
                "source": "forecasting/10_feature_engineering/04_weather",
                "data_source": "develop.eros_analytics_forecasting_scratch.fact_demand_daily + Open-Meteo archive API",
                "formula": "+".join(["entity_fe"] + feature_cols),
            }
        )
        mlflow.log_params(
            {
                "cumulative_features": cumulative_features,
                "holdout_year": run["holdout_year"],
                "n_feature_cols": len(feature_cols),
                "estimator": "PanelOLS(entity_effects=True)",
                "target": "log1p(qty_sold_net)",
                "weather_location_proxy": "state-capital coordinates (dim_locations city names are mock data)",
            }
        )
        for metric, value in run["metrics"].items():
            if isinstance(value, (int, float)) and not pd.isna(value):
                mlflow.log_metric(metric, float(value))
        print(f"Logged run '{run['run_name']}' -> run_id={mlflow_run.info.run_id}")


# %% [markdown]
# ## 4. Fit `baseline+calendar+holidays` (previous run, not re-logged) and
# `baseline+calendar+holidays+weather`, compare against the >2% MAPE threshold

# %%
if __name__ == "__main__":
    cache_path = Path(__file__).resolve().parents[1] / "02_calendar" / "output" / "_weekly_panel.parquet"
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        panel = load_weekly_panel()
        panel.to_parquet(cache_path)

    # The panel extends past the 2025 holdout year (present-day data);
    # fit_and_evaluate() never uses those rows (train < holdout year, eval ==
    # holdout year), but the weather join below would otherwise raise on
    # missing data it fetched no weather for -- truncate first.
    panel = panel[panel["period"] <= WEATHER_END_DATE].copy()

    panel, calendar_cols = add_calendar_features(panel)
    panel, holiday_cols = add_holiday_features(panel)
    panel, weather_cols = add_weather_features(panel)

    prior_cols = calendar_cols + holiday_cols
    previous_run = fit_and_evaluate(panel, prior_cols, "baseline+calendar+holidays")
    weather_run = fit_and_evaluate(panel, prior_cols + weather_cols, "baseline+calendar+holidays+weather")

    print(f"Holdout year: {weather_run['holdout_year']}")
    print("baseline+calendar+holidays metrics (previous run):", previous_run["metrics"])
    print("baseline+calendar+holidays+weather metrics:", weather_run["metrics"])

    prev_mape = previous_run["metrics"]["mape"]
    new_mape = weather_run["metrics"]["mape"]
    mape_improvement = (prev_mape - new_mape) / prev_mape
    meets_threshold = mape_improvement > MAPE_IMPROVEMENT_THRESHOLD
    print(f"MAPE improvement vs. baseline+calendar+holidays: {mape_improvement:.1%} (threshold: >{MAPE_IMPROVEMENT_THRESHOLD:.0%})")
    print(f"Meets threshold: {meets_threshold}")

    coef_table = pd.DataFrame(
        {
            "coefficient": weather_run["result"].params,
            "std_error": weather_run["result"].std_errors,
            "t_stat": weather_run["result"].tstats,
            "p_value": weather_run["result"].pvalues,
        }
    )
    coef_table.to_csv(OUTPUT_DIR / "coefficients.csv")

    metrics_comparison = pd.DataFrame(
        {
            "baseline+calendar+holidays": previous_run["metrics"],
            "baseline+calendar+holidays+weather": weather_run["metrics"],
        }
    )
    metrics_comparison["pct_change"] = (
        metrics_comparison["baseline+calendar+holidays+weather"] - metrics_comparison["baseline+calendar+holidays"]
    ) / metrics_comparison["baseline+calendar+holidays"]
    metrics_comparison.to_csv(OUTPUT_DIR / "metrics_comparison.csv")

    with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
        f.write(
            f"mape_improvement={mape_improvement:.4f}\n"
            f"threshold={MAPE_IMPROVEMENT_THRESHOLD}\n"
            f"meets_threshold={meets_threshold}\n"
        )

    mlflow = init_mlflow_experiment()
    log_run(mlflow, weather_run, prior_cols + weather_cols, "calendar+holidays+weather")
