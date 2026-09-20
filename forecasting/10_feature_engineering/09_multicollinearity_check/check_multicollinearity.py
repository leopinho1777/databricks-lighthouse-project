# %% [markdown]
# # Task 2.9 -- Multicollinearity check (weather vs. calendar terms)
#
# Statistically tests whether task 2.4's weather terms are adding new
# information or just duplicating what month/week-of-year already tells the
# model -- directly motivated by task 2.4's own open question about
# `wind_max`'s counter-intuitive positive sign. Per that report:
#
# > "A high VIF would corroborate that theory; a low VIF would not explain
# > the sign flip at all -- it would mean wind is *not* redundant with
# > calendar, and the counter-intuitive positive coefficient would remain
# > unexplained, not resolved by elimination."
#
# **This task reports whichever of those two outcomes actually happened --
# it does not default to the seasonal-timing theory regardless of the
# result.**
#
# VIF is computed two ways, since the tracker's literal ask ("weather vs.
# calendar") and the current cumulative formula (task 2.6's, per this task's
# instructions) are different scopes:
# 1. **Calendar+weather only** -- the tracker's literal scope, isolating
#    exactly the redundancy question task 2.4's report raised.
# 2. **Full task 2.6 cumulative formula** -- weather's VIF against
#    *everything* currently in the model (holidays, economic, marketing,
#    trend too), which is the more complete picture for this stage's actual
#    formula.
#
# VIF is computed on **entity-demeaned** regressors (the within-transform
# `PanelOLS(entity_effects=True)` actually fits on), not the raw columns --
# collinearity in the raw data is not the same question as collinearity in
# the variation the fixed-effects estimator actually uses to identify
# coefficients.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_holidays"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04_weather"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "05_economic"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "06_marketing"))

import numpy as np
import pandas as pd
from add_calendar_features import add_calendar_features
from add_economic_features import add_economic_features
from add_holiday_features import add_holiday_features
from add_marketing_features import add_marketing_features
from add_weather_features import WEATHER_END_DATE, add_weather_features
from sklearn.linear_model import Ridge
from statsmodels.stats.outliers_influence import variance_inflation_factor

from _shared.panel_regression import KEYS, load_weekly_panel, most_recent_complete_year

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
VIF_HIGH_THRESHOLD = 5.0  # conventional 5-10 range; using the more conservative (easier-to-trigger) end

# %% [markdown]
# ## 1. Build the training panel with every task 2.6 formula column, plus
# `trend` (the same structural control every fit uses)


# %%
def build_training_design() -> tuple[pd.DataFrame, dict[str, list[str]]]:
    cache_path = Path(__file__).resolve().parents[1] / "02_calendar" / "output" / "_weekly_panel.parquet"
    panel = pd.read_parquet(cache_path) if cache_path.exists() else load_weekly_panel()
    panel = panel[panel["period"] <= WEATHER_END_DATE].copy()

    panel, calendar_cols = add_calendar_features(panel)
    panel, holiday_cols = add_holiday_features(panel)
    panel, weather_cols = add_weather_features(panel)
    panel, economic_cols = add_economic_features(panel)
    panel, marketing_cols = add_marketing_features(panel)

    panel["entity"] = panel[KEYS[0]] + "|" + panel[KEYS[1]]
    panel["trend"] = (panel["period"] - panel["period"].min()) / pd.Timedelta(weeks=1)

    holdout_year = most_recent_complete_year(panel["period"])
    train = panel[panel["period"].dt.year < holdout_year].copy()

    groups = {
        "calendar": calendar_cols,
        "holidays": holiday_cols,
        "weather": weather_cols,
        "economic": economic_cols,
        "marketing": marketing_cols,
        "trend": ["trend"],
    }
    return train, groups


# %% [markdown]
# ## 2. VIF on entity-demeaned regressors -- the within-transform
# `PanelOLS(entity_effects=True)` actually fits on, not the raw columns.


# %%
def compute_vif(train: pd.DataFrame, cols: list[str]) -> pd.Series:
    demeaned = train[cols] - train.groupby("entity")[cols].transform("mean")
    X = demeaned.to_numpy()
    return pd.Series({col: variance_inflation_factor(X, i) for i, col in enumerate(cols)})


def fit_ridge_demeaned(train: pd.DataFrame, cols: list[str], alpha: float = 1.0) -> pd.Series:
    """Ridge fallback on the same entity-demeaned design, coefficients only
    (ridge doesn't produce p-values -- it's a stability check on the
    coefficient estimates, not a significance test)."""
    demeaned_X = train[cols] - train.groupby("entity")[cols].transform("mean")
    demeaned_y = train["log_qty"] - train.groupby("entity")["log_qty"].transform("mean")
    model = Ridge(alpha=alpha, fit_intercept=False)
    model.fit(demeaned_X.to_numpy(), demeaned_y.to_numpy())
    return pd.Series(model.coef_, index=cols)


# %% [markdown]
# ## 3. Run both VIF scopes, apply the ridge fallback if warranted

# %%
if __name__ == "__main__":
    train, groups = build_training_design()
    train["log_qty"] = np.log1p(train["qty_sold_net"])

    # --- Scope 1: tracker's literal ask -- calendar + weather only ---
    calendar_weather_cols = groups["calendar"] + groups["weather"]
    vif_calendar_weather = compute_vif(train, calendar_weather_cols)
    vif_calendar_weather.to_csv(OUTPUT_DIR / "vif_calendar_weather_only.csv")
    print("VIF (calendar + weather only):")
    print(vif_calendar_weather.to_string())

    # --- Scope 2: full task 2.6 cumulative formula ---
    full_cols = groups["calendar"] + groups["holidays"] + groups["weather"] + groups["economic"] + groups["marketing"] + groups["trend"]
    vif_full = compute_vif(train, full_cols)
    vif_full.to_csv(OUTPUT_DIR / "vif_full_formula.csv")
    print("\nVIF (full task 2.6 cumulative formula + trend):")
    print(vif_full.to_string())

    weather_vif_full = vif_full[groups["weather"]]
    print(f"\nWeather terms' VIF within the full formula:\n{weather_vif_full.to_string()}")

    high_vif_weather_terms = weather_vif_full[weather_vif_full > VIF_HIGH_THRESHOLD]
    triggered = len(high_vif_weather_terms) > 0
    print(f"\nAny weather term VIF > {VIF_HIGH_THRESHOLD}: {triggered}")

    with open(OUTPUT_DIR / "vif_verdict.txt", "w", encoding="utf-8") as f:
        f.write(f"vif_high_threshold={VIF_HIGH_THRESHOLD}\n")
        f.write(f"triggered_ridge_fallback={triggered}\n")
        f.write(f"weather_vif_full_formula:\n{weather_vif_full.to_string()}\n")
        f.write(f"weather_vif_calendar_only:\n{vif_calendar_weather[groups['weather']].to_string()}\n")

    # --- Ridge fallback, only if warranted ---
    if triggered:
        print("\nVIF exceeded threshold -- fitting ridge-regularized version as the documented fallback.")
        ridge_coefs = fit_ridge_demeaned(train, full_cols)
        ridge_coefs.to_csv(OUTPUT_DIR / "ridge_coefficients.csv")
        print(ridge_coefs.to_string())
    else:
        print("\nVIF did not exceed threshold -- ridge fallback not triggered, not fit.")
