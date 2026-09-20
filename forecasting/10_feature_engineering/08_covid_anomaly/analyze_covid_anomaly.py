# %% [markdown]
# # Task 2.8 -- COVID anomaly investigation
#
# Independent of the cumulative feature chain (2.2-2.7) -- this task asks
# whether 2020-2021 deviates from the surrounding trend, and produces a
# written recommendation for the team, not a unilateral change to the
# training window.
#
# **Starting point, not ignored**: `01_data_exploration_summary.md` section 3
# already ran this exact check at the portfolio-revenue level and found no
# anomaly ("growth looks like a smooth, designed trend line... nothing here
# to adjust for"). This script does two things that check are independent
# from and complementary to: (1) reconciling that finding on `qty_sold_net`
# specifically (Phase 1 used gross revenue from `fct_sales`), with charts,
# and (2) checking whether 2020/2021 show a distinct RESIDUAL pattern once
# seasonality and entity level are controlled for, using task 2.2's own
# already-fitted `baseline+calendar` model -- a different, model-based lens
# Phase 1's raw-total comparison couldn't provide.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_calendar"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from add_calendar_features import add_calendar_features

from _shared.panel_regression import fit_and_evaluate, load_weekly_panel

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# %% [markdown]
# ## 1. Portfolio-total qty_sold_net by year -- reconciles Phase 1's
# revenue-based table using the quantity metric this stage's panel is built
# on.

# %%
if __name__ == "__main__":
    cache_path = Path(__file__).resolve().parents[1] / "02_calendar" / "output" / "_weekly_panel.parquet"
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        panel = load_weekly_panel()
        panel.to_parquet(cache_path)

    panel["year"] = panel["period"].dt.year
    panel["month"] = panel["period"].dt.month

    # The panel's first period-week (Monday 2019-12-30) is labeled year 2019
    # by ISO-week convention but holds only that single stray week's data --
    # a real 2019 doesn't exist in this dataset. Dropped from the yearly
    # comparison so it doesn't produce a meaningless "+4586%" artifact on the
    # 2020 row; kept in the monthly-shape chart's underlying data is moot
    # since month 12 2019 has no other weeks to join into anyway.
    yearly_totals = panel[panel["year"] >= 2020].groupby("year", as_index=False)["qty_sold_net"].sum()
    yearly_totals["yoy_pct"] = yearly_totals["qty_sold_net"].pct_change() * 100
    yearly_totals.to_csv(OUTPUT_DIR / "yearly_totals.csv", index=False)
    print(yearly_totals.to_string(index=False))

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(yearly_totals["year"].astype(str), yearly_totals["qty_sold_net"], color="#4C72B0")
    for bar, pct in zip(bars, yearly_totals["yoy_pct"]):
        if pd.notna(pct):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{pct:+.1f}%",
                     ha="center", va="bottom", fontsize=9)
    ax.set_title("Portfolio-total qty_sold_net by year")
    ax.set_ylabel("qty_sold_net (sum across all product x location series)")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "yearly_totals.png", dpi=120)
    plt.close(fig)

    # %% [markdown]
    # ## 2. Monthly seasonal shape overlay by year -- checks whether
    # 2020/2021's *shape* (not just level) deviates from other years, which
    # Phase 1's annual-total + Jan-Aug comparison couldn't directly show.

    # %%
    monthly = panel[panel["year"] >= 2020].groupby(["year", "month"], as_index=False)["qty_sold_net"].sum()
    monthly_pivot = monthly.pivot(index="month", columns="year", values="qty_sold_net")
    monthly_pivot.to_csv(OUTPUT_DIR / "monthly_by_year.csv")

    fig, ax = plt.subplots(figsize=(9, 5))
    for year in monthly_pivot.columns:
        style = "--" if year in (2020, 2021) else "-"
        width = 2.5 if year in (2020, 2021) else 1.2
        ax.plot(monthly_pivot.index, monthly_pivot[year], style, linewidth=width, label=str(year))
    ax.set_title("Monthly qty_sold_net by year (2020-2021 dashed)")
    ax.set_xlabel("month")
    ax.set_ylabel("qty_sold_net")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "monthly_shape_by_year.png", dpi=120)
    plt.close(fig)

    # %% [markdown]
    # ## 3. Residual check using task 2.2's already-fitted `baseline+calendar`
    # model -- does 2020/2021 show a distinct residual pattern once
    # seasonality and entity level are controlled for?

    # %%
    calendar_panel, calendar_cols = add_calendar_features(panel[panel["period"] <= "2025-12-31"].copy())
    calendar_run = fit_and_evaluate(calendar_panel, calendar_cols, "baseline+calendar_covid_check")
    resids = calendar_run["result"].resids
    resids_df = resids.reset_index()
    resids_df.columns = ["entity", "period", "residual"]
    resids_df["year"] = resids_df["period"].dt.year

    residual_by_year = resids_df.groupby("year")["residual"].agg(["mean", "std", "count"]).reset_index()
    residual_by_year.to_csv(OUTPUT_DIR / "residual_by_year.csv", index=False)
    print(residual_by_year.to_string(index=False))
