# %% [markdown]
# # Task 2.5 -- Add economic features
#
# Builds on task 2.4's `baseline+calendar+holidays+weather` formula. Economic
# indicators don't exist anywhere in this project beyond FX rates used for
# currency conversion (confirmed during exploration before this stage
# started) -- sourced from BCB's free SGS API (Banco Central do Brasil), not
# the tracker's literal FRED (US) suggestion, since the business is Brazilian
# (confirmed with the team before this stage started).
#
# `baseline+calendar+holidays+weather` is refit here in-memory purely to
# compute this task's delta -- not re-logged (task 2.4 already logged it).
# Only `baseline+calendar+holidays+weather+economic` is logged as a new run.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_holidays"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04_weather"))

import pandas as pd
import requests
from add_calendar_features import add_calendar_features
from add_holiday_features import add_holiday_features
from add_weather_features import add_weather_features, WEATHER_END_DATE, WEATHER_START_DATE

from _shared.panel_regression import fit_and_evaluate, init_mlflow_experiment, load_weekly_panel

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MAPE_IMPROVEMENT_THRESHOLD = 0.02
SELIC_SERIES = 432  # Taxa de juros - Selic (daily, % a.a.)
IPCA_SERIES = 433  # IPCA - variacao mensal (%)

# %% [markdown]
# ## 1. BCB SGS series -- both national-level, no location join needed.
# SELIC is daily (aggregated to weekly mean); IPCA is monthly (broadcast to
# every week within that month, since it's only ever published once/month).


# %%
def fetch_bcb_series(series_code: int) -> pd.DataFrame:
    start = pd.Timestamp(WEATHER_START_DATE).strftime("%d/%m/%Y")
    end = pd.Timestamp(WEATHER_END_DATE).strftime("%d/%m/%Y")
    resp = requests.get(
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados",
        params={"formato": "json", "dataInicial": start, "dataFinal": end},
        timeout=60,
    )
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    df["date"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["value"] = df["valor"].astype(float)
    return df[["date", "value"]]


def load_economic_weekly() -> pd.DataFrame:
    cache_path = OUTPUT_DIR / "_economic_raw.parquet"
    if cache_path.exists():
        raw = pd.read_parquet(cache_path)
    else:
        selic = fetch_bcb_series(SELIC_SERIES).rename(columns={"value": "selic_rate"})
        ipca = fetch_bcb_series(IPCA_SERIES).rename(columns={"value": "ipca_monthly_variation"})
        raw = selic.merge(ipca, on="date", how="outer").sort_values("date")
        raw.to_parquet(cache_path)

    raw = raw.sort_values("date").set_index("date")
    # SELIC is published daily; IPCA only once a month (on the 1st) -- forward
    # fill IPCA so every day carries that month's latest published reading,
    # matching how a real forecasting pipeline would only know the latest
    # release, not future months' values.
    raw["ipca_monthly_variation"] = raw["ipca_monthly_variation"].ffill()
    raw = raw.reset_index()

    raw["week_start"] = raw["date"] - pd.to_timedelta(raw["date"].dt.weekday, unit="D")
    weekly = (
        raw.groupby("week_start")
        .agg(selic_rate=("selic_rate", "mean"), ipca_monthly_variation=("ipca_monthly_variation", "mean"))
        .reset_index()
    )
    return weekly


# %% [markdown]
# ## 2. Join onto the panel (national-level, same value for every location)


# %%
def add_economic_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    weekly_economic = load_economic_weekly()
    df = df.merge(weekly_economic, left_on="period", right_on="week_start", how="left").drop(columns=["week_start"])
    feature_cols = ["selic_rate", "ipca_monthly_variation"]
    missing = df[feature_cols].isna().any(axis=1).sum()
    if missing:
        raise ValueError(f"{missing} panel rows have no matching economic data -- check date range coverage")
    return df, feature_cols


# %% [markdown]
# ## 3. MLflow logging (new run only)


# %%
def log_run(mlflow, run: dict, feature_cols: list[str], cumulative_features: str):
    with mlflow.start_run(run_name=run["run_name"]) as mlflow_run:
        mlflow.set_tags(
            {
                "phase": "2_feature_engineering",
                "task_ids": "2.5",
                "grain": "product_variant_id x location_id (SKU x Store) x ISO week",
                "source": "forecasting/10_feature_engineering/05_economic",
                "data_source": "develop.eros_analytics_forecasting_scratch.fact_demand_daily + BCB SGS API",
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
                "economic_data_source": "BCB SGS (series 432 SELIC, 433 IPCA) -- Brazil, not FRED",
            }
        )
        for metric, value in run["metrics"].items():
            if isinstance(value, (int, float)) and not pd.isna(value):
                mlflow.log_metric(metric, float(value))
        print(f"Logged run '{run['run_name']}' -> run_id={mlflow_run.info.run_id}")


# %% [markdown]
# ## 4. Fit `baseline+calendar+holidays+weather` (previous run, not
# re-logged) and `+economic`, compare against the >2% MAPE threshold

# %%
if __name__ == "__main__":
    cache_path = Path(__file__).resolve().parents[1] / "02_calendar" / "output" / "_weekly_panel.parquet"
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        panel = load_weekly_panel()
        panel.to_parquet(cache_path)

    panel = panel[panel["period"] <= WEATHER_END_DATE].copy()

    panel, calendar_cols = add_calendar_features(panel)
    panel, holiday_cols = add_holiday_features(panel)
    panel, weather_cols = add_weather_features(panel)
    panel, economic_cols = add_economic_features(panel)

    prior_cols = calendar_cols + holiday_cols + weather_cols
    previous_run = fit_and_evaluate(panel, prior_cols, "baseline+calendar+holidays+weather")
    economic_run = fit_and_evaluate(panel, prior_cols + economic_cols, "baseline+calendar+holidays+weather+economic")

    print(f"Holdout year: {economic_run['holdout_year']}")
    print("baseline+calendar+holidays+weather metrics (previous run):", previous_run["metrics"])
    print("+economic metrics:", economic_run["metrics"])

    prev_mape = previous_run["metrics"]["mape"]
    new_mape = economic_run["metrics"]["mape"]
    mape_improvement = (prev_mape - new_mape) / prev_mape
    meets_threshold = mape_improvement > MAPE_IMPROVEMENT_THRESHOLD
    print(
        f"MAPE improvement vs. baseline+calendar+holidays+weather: {mape_improvement:.2%} "
        f"(threshold: >{MAPE_IMPROVEMENT_THRESHOLD:.0%})"
    )
    print(f"Meets threshold: {meets_threshold}")

    coef_table = pd.DataFrame(
        {
            "coefficient": economic_run["result"].params,
            "std_error": economic_run["result"].std_errors,
            "t_stat": economic_run["result"].tstats,
            "p_value": economic_run["result"].pvalues,
        }
    )
    coef_table.to_csv(OUTPUT_DIR / "coefficients.csv")

    metrics_comparison = pd.DataFrame(
        {
            "baseline+calendar+holidays+weather": previous_run["metrics"],
            "+economic": economic_run["metrics"],
        }
    )
    metrics_comparison["pct_change"] = (
        metrics_comparison["+economic"] - metrics_comparison["baseline+calendar+holidays+weather"]
    ) / metrics_comparison["baseline+calendar+holidays+weather"]
    metrics_comparison.to_csv(OUTPUT_DIR / "metrics_comparison.csv")

    with open(OUTPUT_DIR / "verdict.txt", "w", encoding="utf-8") as f:
        f.write(
            f"mape_improvement={mape_improvement:.4f}\n"
            f"threshold={MAPE_IMPROVEMENT_THRESHOLD}\n"
            f"meets_threshold={meets_threshold}\n"
        )

    mlflow = init_mlflow_experiment()
    log_run(mlflow, economic_run, prior_cols + economic_cols, "calendar+holidays+weather+economic")
