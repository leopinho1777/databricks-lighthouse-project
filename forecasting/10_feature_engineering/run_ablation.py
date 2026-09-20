# %% [markdown]
# # Task 2.10 -- Ablation on the final assembled formula
#
# Required by the approved Stage 2 plan (see `00_feature_backlog.md`'s
# structural-control and methodological-note sections, and its "Required at
# task 2.10" paragraph): every layer that stayed in the cumulative testing
# chain without individually clearing the >2% MAPE-improvement threshold
# gets this ablation, not just calendar/holidays -- calendar, holidays,
# weather, economic, and marketing all fall in that category (only
# inventory, task 2.7, added nothing to ablate). This script runs the
# actual ablation rather than deciding by prose: fit the final assembled
# formula (everything tested through task 2.6) with vs. without each layer,
# and compare MAPE. If removing a layer doesn't hurt accuracy, it's dropped
# from the production feature set even though it stayed in the testing
# chain throughout.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "02_calendar"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "03_holidays"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "04_weather"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "05_economic"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "06_marketing"))

import pandas as pd
from add_calendar_features import add_calendar_features
from add_economic_features import add_economic_features
from add_holiday_features import add_holiday_features
from add_marketing_features import add_marketing_features
from add_weather_features import WEATHER_END_DATE, add_weather_features

from _shared.panel_regression import fit_and_evaluate, load_weekly_panel

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# %%
if __name__ == "__main__":
    cache_path = Path(__file__).resolve().parents[0] / "02_calendar" / "output" / "_weekly_panel.parquet"
    panel = pd.read_parquet(cache_path) if cache_path.exists() else load_weekly_panel()
    panel = panel[panel["period"] <= WEATHER_END_DATE].copy()

    panel, calendar_cols = add_calendar_features(panel)
    panel, holiday_cols = add_holiday_features(panel)
    panel, weather_cols = add_weather_features(panel)
    panel, economic_cols = add_economic_features(panel)
    panel, marketing_cols = add_marketing_features(panel)

    layers = {
        "calendar": calendar_cols,
        "holidays": holiday_cols,
        "weather": weather_cols,
        "economic": economic_cols,
        "marketing": marketing_cols,
    }
    full_cols = [c for cols in layers.values() for c in cols]

    full_run = fit_and_evaluate(panel, full_cols, "ablation_full")
    full_mape = full_run["metrics"]["mape"]

    metrics_table = {"full (all five layers)": full_run["metrics"]}
    contributions = {}
    for name, cols in layers.items():
        without_cols = [c for layer_name, layer_cols in layers.items() if layer_name != name for c in layer_cols]
        run = fit_and_evaluate(panel, without_cols, f"ablation_no_{name}")
        metrics_table[f"full minus {name}"] = run["metrics"]
        # Positive = removing the layer made MAPE worse (i.e. the layer was
        # helping); negative or ~zero = removing it didn't hurt (drop it).
        contributions[name] = (run["metrics"]["mape"] - full_mape) / full_mape

    results = pd.DataFrame(metrics_table)
    results.to_csv(OUTPUT_DIR / "ablation_results.csv")
    print(results.loc[["rmse", "bias", "mape", "smape"]].to_string())

    print("\nEach layer's contribution to the full formula (removing it changes MAPE by):")
    for name, contribution in contributions.items():
        print(f"  {name}: {contribution:+.4%}")

    with open(OUTPUT_DIR / "ablation_verdict.txt", "w", encoding="utf-8") as f:
        f.write(f"full_mape={full_mape:.6f}\n")
        for name, contribution in contributions.items():
            f.write(f"{name}_contribution_pct={contribution:.6%}\n")
            f.write(f"{name}_mape_without={metrics_table[f'full minus {name}']['mape']:.6f}\n")

    # %% [markdown]
    # ## Sub-ablation: does calendar need its Fourier terms?
    #
    # Task 2.9 found `week_of_year_sin`/`week_of_year_cos` heavily collinear
    # with the month dummies (VIF up to 44). Calendar as a whole earns its
    # place in the production feature set (see above), but that doesn't
    # settle whether the *Fourier terms specifically* pull their weight
    # within calendar -- tested directly here, on the same full formula,
    # rather than inferred from VIF or in-sample p-values alone.

    # %%
    month_cols = [c for c in calendar_cols if c.startswith("month_")]
    fourier_variants = {
        "month+sin+cos (current)": calendar_cols,
        "month+cos only (drop sin)": month_cols + ["week_of_year_cos"],
        "month only (drop sin+cos)": month_cols,
    }
    other_cols = holiday_cols + weather_cols + economic_cols + marketing_cols
    fourier_results = {}
    for name, cal_cols in fourier_variants.items():
        run = fit_and_evaluate(panel, cal_cols + other_cols, name)
        fourier_results[name] = run["metrics"]["mape"]

    print("\nCalendar Fourier-term sub-ablation (MAPE, full formula otherwise unchanged):")
    for name, mape in fourier_results.items():
        print(f"  {name}: {mape:.7f}")

    pd.Series(fourier_results).to_csv(OUTPUT_DIR / "calendar_fourier_ablation.csv")
