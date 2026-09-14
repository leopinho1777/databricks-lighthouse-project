# %% [markdown]
# # Task 1.6 — Rolling-origin (walk-forward) validation
#
# No walk-forward/rolling-origin code existed anywhere in this repo before this
# stage (checked via repo-wide grep for `walk_forward`/`rolling_origin`). Grain
# -agnostic on purpose (`freq` accepts any pandas offset alias, e.g. "D" for
# daily, "W-MON" for weekly) so the same function backs both the daily-grain
# baseline in this stage and any future weekly/monthly model.
#
# Pure functions only, no DB access or top-level side effects, so importing
# this module elsewhere (as `04`-`07` already do with `03`'s
# `most_recent_complete_year`/`compute_metrics`) never re-runs a query.

# %%
import pandas as pd


def walk_forward_validate(panel: pd.DataFrame, forecast_fn, cutoffs, horizon: int, keys: list, freq: str = "D") -> pd.DataFrame:
    """Roll a cutoff forward through `cutoffs`, scoring `horizon` periods ahead each time.

    `panel` must have columns `keys` + ["period", <a demand column>], one row
    per (series, period) at the cadence implied by `freq`. `forecast_fn(train_df,
    cutoff, horizon, freq) -> DataFrame[keys + ["period", "pred"]]` is the
    pluggable slot — no-lookahead is structural: `forecast_fn` only ever
    receives rows with `period <= cutoff`, and this function asserts that on
    every fold.
    """
    results = []
    for cutoff in cutoffs:
        train = panel[panel["period"] <= cutoff]
        horizon_periods = pd.date_range(cutoff, periods=horizon + 1, freq=freq)[1:]
        actual = panel[panel["period"].isin(horizon_periods)]
        pred = forecast_fn(train, cutoff, horizon, freq)

        assert train["period"].max() <= cutoff, "forecast_fn leaked a train row past cutoff"
        if len(actual):
            assert actual["period"].min() > cutoff, "actual window starts before cutoff"

        merged = actual.merge(pred, on=keys + ["period"], how="left")
        merged["cutoff"] = cutoff
        results.append(merged)
    return pd.concat(results, ignore_index=True)


def make_periodic_cutoffs(train_end: pd.Timestamp, validate_end: pd.Timestamp, horizon: int, step: int, freq: str = "D"):
    """First cutoff = train_end. Step forward by `step` periods of `freq` until
    a full `horizon`-period window still fits inside `validate_end`."""
    cutoffs = []
    cutoff = train_end
    while True:
        window_end = pd.date_range(cutoff, periods=horizon + 1, freq=freq)[-1]
        if window_end > validate_end:
            break
        cutoffs.append(cutoff)
        cutoff = pd.date_range(cutoff, periods=step + 1, freq=freq)[-1]
    return cutoffs


# %%
if __name__ == "__main__":
    # Mechanics smoke test: no DB access, synthetic data only.
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    demo_panel = pd.DataFrame({"sku": "A", "period": dates, "qty": range(len(dates))})

    def _trivial_forecast(train_df, cutoff, horizon, freq):
        horizon_periods = pd.date_range(cutoff, periods=horizon + 1, freq=freq)[1:]
        level = train_df["qty"].tail(28).mean()
        return pd.DataFrame({"sku": "A", "period": horizon_periods, "pred": level})

    cutoffs = make_periodic_cutoffs(pd.Timestamp("2024-12-31"), pd.Timestamp("2025-12-31"), horizon=91, step=91, freq="D")
    demo = walk_forward_validate(demo_panel, _trivial_forecast, cutoffs, horizon=91, keys=["sku"], freq="D")
    print(f"Cutoffs: {[c.date() for c in cutoffs]}")
    print(f"Rows scored: {len(demo)}, folds: {demo['cutoff'].nunique()}")
    assert demo["cutoff"].nunique() == len(cutoffs)
    print("Mechanics smoke test passed.")
