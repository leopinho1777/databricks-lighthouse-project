# %%
"""Stage 3 task 3.7 -- final side-by-side comparison of every model, from committed outputs only.

No model is refit here. Every candidate already wrote `<run>_window_totals.csv` (one row per
(product_variant_id, location_id, cutoff) with the 91-day `actual` and `pred` totals), so this script
re-scores them all through the same `experiments/_shared/evaluate.py` protocol and lines them up
against the committed `seasonal_naive_genuine_91d_v2` baseline, exactly as `compare_to_baseline()` does.
Nothing under `09_baseline_close_out/` is touched or recomputed.

Outputs (small tracked CSVs in `output/`):
  comparison_sku_portfolio.csv       per model x window, SKU x location, vs. the champion
  comparison_category_portfolio.csv  per model x window, category x location (same predictions, summed up)
  comparison_summary.csv             one row per model: wins, mean WAPE, peak/off-peak WAPE, bias, RMSE
  data_behavior_evidence.csv         per window: zero-sales share, Poisson noise floor, peak flag
  zero_actual_forecast_mass.csv      per model x window: forecast mass placed on series that sold nothing
  convention_sensitivity.csv         per model x window: WAPE on all series vs. on actual > 0 series only
  report_tables.md                   the Markdown tables pasted into the report (no hand-retyping)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
EXPERIMENTS = HERE.parent / "experiments"

# The protocol module is imported by file path, not package name: the repo has three `_shared` directories.
sys.path.insert(0, str(EXPERIMENTS / "_shared"))
from evaluate import KEYS, compare_to_baseline, evaluate, get_cutoffs, load_baseline_portfolio, to_category_level  # noqa: E402

BASELINE_NAME = "seasonal_naive (champion)"
HORIZON_DAYS = 91
# Peak months derived from data <= 2024-12-31 in every Stage 3 script (see pinho_sarima/README.md).
PEAK_MONTHS = [1, 2, 3, 4, 10, 11, 12]
# Tolerance when checking our recomputed WAPE against each run's own compare_to_baseline.csv.
WAPE_CHECK_TOLERANCE_PP = 0.01


# %% [markdown]
# ## 1. Run registry
#
# One entry per committed configuration. `window_def` matters for interpretation: `exact` means the
# window is exactly cutoff+1 .. cutoff+91; `weekly-straddle` means a weekly-grain fit that drops the
# Monday-anchored week straddling the cutoff, so the scored window is shifted by up to ~5 days and
# `actual_total` drifts from the baseline's (up to 9.49% on 2025-07-01).

# %%
def _run(name, family, owner, window_csv, compare_csv, target, window_def, tuning):
    """Registry row for one committed configuration."""
    return {
        "name": name,
        "family": family,
        "owner": owner,
        "window_csv": EXPERIMENTS / window_csv,
        "compare_csv": EXPERIMENTS / compare_csv,
        "target": target,
        "window_def": window_def,
        "tuning": tuning,
    }


def _rf(tag, label):
    return _run(
        f"RF {label}", "Random Forest", "eros_randomforest",
        f"eros_randomforest/output/random_forest_{tag}_window_totals.csv",
        f"eros_randomforest/output/random_forest_{tag}_compare_to_baseline.csv",
        "log1p", "weekly-straddle", "one-parameter-at-a-time sweep (5 configs)",
    )


def _prophet(tag, label):
    return _run(
        f"Prophet {label}", "Prophet", "eros_prophet",
        f"eros_prophet/output/prophet_{tag}_window_totals.csv",
        f"eros_prophet/output/prophet_{tag}_compare_to_baseline.csv",
        "log1p", "weekly-straddle", "one-parameter-at-a-time sweep (5 configs)",
    )


def _sarima(tag, label):
    return _run(
        f"SARIMA {label}", "SARIMA", "pinho_sarima",
        f"pinho_sarima/output/sarima_{tag}_window_totals.csv",
        f"pinho_sarima/output/sarima_{tag}_compare_to_baseline.csv",
        "log1p", "weekly-straddle", "fixed order, no per-series search (2 configs)",
    )


def _panel(tag, label):
    return _run(
        f"Panel regression {label}", "FE panel regression", "eva_regression",
        f"eva_regression/output/panel_regression_fe_trend_month{tag}_window_totals.csv",
        f"eva_regression/output/panel_regression_fe_trend_month{tag}_baseline_comparison.csv",
        "log1p", "exact (weekly fit, prorated by day)", "none (Stage 2 specification)",
    )


RUNS = [
    _rf("baseline", "unbounded"), _rf("depth10", "depth10"), _rf("depth20", "depth20"),
    _rf("leaf20", "leaf20"), _rf("sqrtfeatures", "sqrtfeatures"),
    _prophet("baseline", "default"), _prophet("changepoint_flexible", "changepoint flexible"),
    _prophet("changepoint_rigid", "changepoint rigid"),
    _prophet("seasonality_multiplicative", "multiplicative seasonality"), _prophet("no_holidays", "no holidays"),
    _sarima("baseline", "d=1"), _sarima("d0_trend", "d=0 + trend"),
    _run(
        "XGBoost v1", "XGBoost", "gabriel_xgboost",
        "gabriel_xgboost/output/xgboost_v1_window_totals.csv",
        "gabriel_xgboost/output/xgboost_v1_compare_to_baseline.csv",
        "raw counts", "exact", "Hyperopt, 30 evals on an earlier fold",
    ),
    _panel("", "(uncorrected)"), _panel("_smearing", "+ Duan smearing"),
]
# Families where both variants stay in the main table (the uncorrected and smearing runs are a pair).
KEEP_BOTH_FAMILIES = {"FE panel regression"}


# %% [markdown]
# ## 2. Scoring helpers

# %%
def load_window_totals(run: dict) -> pd.DataFrame:
    """Read one run's committed window totals and validate its shape (6,054 series x 4 windows)."""
    df = pd.read_csv(run["window_csv"])
    df["cutoff"] = pd.to_datetime(df["cutoff"])
    df = df[[*KEYS, "cutoff", "actual", "pred"]]
    n_series = df[KEYS].drop_duplicates().shape[0]
    assert n_series == 6054 and df["cutoff"].nunique() == 4 and len(df) == 6054 * 4, (
        f"{run['name']}: expected 6,054 series x 4 windows, got {n_series} series / {len(df)} rows"
    )
    return df


def check_against_own_report(run: dict, portfolio: pd.DataFrame) -> None:
    """Assert our recomputed portfolio WAPE matches the number the run itself reported."""
    own = pd.read_csv(run["compare_csv"])
    own["cutoff"] = pd.to_datetime(own["cutoff"])
    merged = portfolio.merge(own[["cutoff", "wape_pct"]], on="cutoff", suffixes=("", "_own"))
    assert len(merged) == 4, f"{run['name']}: cutoffs do not line up with the run's own report"
    worst = (merged["wape_pct"] - merged["wape_pct_own"]).abs().max()
    assert worst < WAPE_CHECK_TOLERANCE_PP, f"{run['name']}: WAPE differs from its own report by {worst:.3f}pp"


def peak_flags(cutoffs) -> pd.DataFrame:
    """Share of each 91-day window's days that fall in a peak month; peak window = majority of days."""
    rows = []
    for cutoff in cutoffs:
        days = pd.date_range(cutoff + pd.Timedelta(days=1), periods=HORIZON_DAYS)
        share = float(days.month.isin(PEAK_MONTHS).mean())
        rows.append({"cutoff": cutoff, "peak_day_share": share, "is_peak_window": share >= 0.5})
    return pd.DataFrame(rows)


def pooled_wape(portfolio: pd.DataFrame, mask: pd.Series) -> float:
    """Pooled WAPE over the selected windows: sum of abs errors / sum of actual (abs error = wape x actual)."""
    sel = portfolio[mask]
    return 100 * (sel["wape_pct"] / 100 * sel["actual_total"]).sum() / sel["actual_total"].sum()


def zero_actual_mass(df: pd.DataFrame) -> pd.DataFrame:
    """Per window: share of series that sold nothing, and the forecast units placed on them."""
    return (
        df.groupby("cutoff")
        .apply(
            lambda g: pd.Series(
                {
                    "pct_series_zero_actual": 100 * (g["actual"] == 0).mean(),
                    "forecast_on_zero_series": g.loc[g["actual"] == 0, "pred"].sum(),
                    "forecast_total": g["pred"].sum(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )


def convention_sensitivity(windows: dict) -> pd.DataFrame:
    """Per model x window: WAPE on all series vs. on series with actual > 0 only.

    The committed baseline WAPE only counts series that sold something in the window, while `evaluate()`
    scores all 6,054. This shows how much each model's WAPE moves if it is scored the baseline's way.
    """
    rows = []
    for name, df in windows.items():
        for cutoff, g in df.groupby("cutoff"):
            positive = g[g["actual"] > 0]
            rows.append(
                {
                    "model": name,
                    "cutoff": cutoff,
                    "wape_all_series": 100 * (g["actual"] - g["pred"]).abs().sum() / g["actual"].sum(),
                    "wape_actual_positive_only": 100 * (positive["actual"] - positive["pred"]).abs().sum() / positive["actual"].sum(),
                }
            )
    return pd.DataFrame(rows)


def poisson_noise_floor(df: pd.DataFrame) -> pd.DataFrame:
    """Best-case WAPE if each series' rate were known exactly and demand were Poisson (an optimistic floor).

    Rate per series = its 4-window mean actual, scaled by that window's share of total volume so the
    seasonal swing is kept. Real demand is over-dispersed (observed zero-share far above the Poisson
    prediction), so the true floor is higher than this.
    """
    lam_series = df.groupby(KEYS)["actual"].mean()
    totals = df.groupby("cutoff")["actual"].sum()
    scale = totals / totals.mean()

    def mean_abs_dev(lam: float) -> float:
        ks = np.arange(0, int(lam + 12 * np.sqrt(lam + 1) + 20))
        return float((stats.poisson.pmf(ks, lam) * np.abs(ks - lam)).sum())

    rows = []
    for cutoff, s in scale.items():
        lam = (lam_series * s).to_numpy()
        rows.append(
            {
                "cutoff": cutoff,
                "actual_total": totals[cutoff],
                "mean_actual_per_series": totals[cutoff] / len(lam),
                "observed_pct_zero": 100 * (df.loc[df["cutoff"] == cutoff, "actual"] == 0).mean(),
                "poisson_pct_zero": 100 * float(np.exp(-lam).mean()),
                "poisson_floor_wape_pct": 100 * sum(mean_abs_dev(x) for x in lam) / lam.sum(),
            }
        )
    return pd.DataFrame(rows)


# %% [markdown]
# ## 3. Score every committed run

# %%
def score_all():
    """Score each run at SKU and category level; return the long tables and the per-run summary."""
    cutoffs = get_cutoffs()
    flags = peak_flags(cutoffs)
    baseline = load_baseline_portfolio()

    sku_rows, cat_rows, mass_rows, summary_rows = [], [], [], []
    windows = {}

    # Champion row first: portfolio numbers only (per-series metrics are not comparable, see the report).
    base = baseline.merge(flags, on="cutoff")
    base["bias_pct"] = 100 * base["bias"] / base["actual_total"]
    base_sku = base.assign(model=BASELINE_NAME, family="Baseline", wape_pct_baseline=base["wape_pct"], wape_delta_pp=0.0)
    sku_rows.append(base_sku)
    summary_rows.append(
        {
            "model": BASELINE_NAME, "family": "Baseline", "owner": "09_baseline_close_out", "target": "n/a",
            "window_def": "exact", "windows_beating_baseline": 0,
            "wape_mean": base["wape_pct"].mean(), "wape_peak": pooled_wape(base, base["is_peak_window"]),
            "wape_offpeak": pooled_wape(base, ~base["is_peak_window"]), "bias_pct_mean": base["bias_pct"].mean(),
            "rmse_mean": np.nan, "rmse_median": np.nan, "bias_mean_per_series": np.nan,
            "cat_wape_mean": np.nan, "cat_wape_min": np.nan, "cat_wape_max": np.nan,
        }
    )

    for run in RUNS:
        df = load_window_totals(run)
        windows[run["name"]] = df

        sku = evaluate(df)
        check_against_own_report(run, sku["portfolio"])
        cmp = compare_to_baseline(sku["portfolio"])
        port = sku["portfolio"].merge(cmp[["cutoff", "wape_pct_baseline", "wape_delta_pp", "beats_baseline"]], on="cutoff")
        port = port.merge(flags, on="cutoff")
        port["bias_pct"] = 100 * port["bias"] / port["actual_total"]
        sku_rows.append(port.assign(model=run["name"], family=run["family"]))

        cat = evaluate(to_category_level(df), keys=["category_name", "location_id"])["portfolio"].merge(flags, on="cutoff")
        cat_rows.append(cat.assign(model=run["name"], family=run["family"]))

        mass_rows.append(zero_actual_mass(df).assign(model=run["name"]))

        summ = sku["per_series_summary"].iloc[0]
        summary_rows.append(
            {
                "model": run["name"], "family": run["family"], "owner": run["owner"], "target": run["target"],
                "window_def": run["window_def"], "windows_beating_baseline": int(port["beats_baseline"].sum()),
                "wape_mean": port["wape_pct"].mean(), "wape_peak": pooled_wape(port, port["is_peak_window"]),
                "wape_offpeak": pooled_wape(port, ~port["is_peak_window"]), "bias_pct_mean": port["bias_pct"].mean(),
                "rmse_mean": summ["rmse_mean"], "rmse_median": summ["rmse_median"], "bias_mean_per_series": summ["bias_mean"],
                "cat_wape_mean": cat["wape_pct"].mean(), "cat_wape_min": cat["wape_pct"].min(), "cat_wape_max": cat["wape_pct"].max(),
            }
        )

    sku_long = pd.concat(sku_rows, ignore_index=True)
    cat_long = pd.concat(cat_rows, ignore_index=True)
    mass_long = pd.concat(mass_rows, ignore_index=True)
    summary = pd.DataFrame(summary_rows)
    return sku_long, cat_long, mass_long, summary, windows, flags


def mark_main_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Flag the main-table rows: the champion, the lowest-mean-WAPE config per family, and both panel variants."""
    summary = summary.copy()
    trained = summary[summary["family"] != "Baseline"]
    best = trained.loc[trained.groupby("family")["wape_mean"].idxmin(), "model"].tolist()
    keep_both = trained.loc[trained["family"].isin(KEEP_BOTH_FAMILIES), "model"].tolist()
    summary["in_main_table"] = summary["model"].isin([BASELINE_NAME, *best, *keep_both])
    return summary


# %% [markdown]
# ## 4. Markdown tables for the report

# %%
def _fmt(value, spec: str) -> str:
    return "n/a" if pd.isna(value) else format(value, spec)


def md_table(header: list, rows: list) -> str:
    """Render a GitHub-flavoured Markdown table from a header and a list of row lists."""
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def build_report_tables(sku_long, cat_long, summary, evidence, mass_long, sensitivity) -> str:
    """All tables the report quotes, generated from the same frames that back the CSVs."""
    order = summary.sort_values(["in_main_table", "wape_mean"], ascending=[False, True])
    main = order[order["in_main_table"]]
    cutoffs = sorted(sku_long["cutoff"].unique())
    cut_labels = [pd.Timestamp(c).strftime("%Y-%m-%d") for c in cutoffs]
    flag = sku_long.drop_duplicates("cutoff").set_index("cutoff")["is_peak_window"]
    out = []

    def per_window(long_df, model, col):
        sub = long_df[long_df["model"] == model].set_index("cutoff")[col]
        return [sub[c] for c in cutoffs]

    # Main SKU-level table: WAPE per window, then aggregates
    header = ["Model", *[f"{lbl}{' (peak)' if flag[c] else ''}" for c, lbl in zip(cutoffs, cut_labels)],
              "Mean", "Peak", "Off-peak", "Wins vs champion"]
    rows = []
    for _, r in main.iterrows():
        vals = per_window(sku_long, r["model"], "wape_pct")
        rows.append([r["model"], *[f"{v:.1f}" for v in vals], f"{r['wape_mean']:.1f}", f"{r['wape_peak']:.1f}",
                     f"{r['wape_offpeak']:.1f}", "-" if r["family"] == "Baseline" else f"{r['windows_beating_baseline']}/4"])
    out += ["### SKU x location portfolio WAPE (%), main table", md_table(header, rows), ""]

    # Bias and per-series error
    header = ["Model", "Mean portfolio bias (% of actual)", "Per-series RMSE mean", "Per-series RMSE median", "Per-series bias mean"]
    rows = [[r["model"], _fmt(r["bias_pct_mean"], ".1f"), _fmt(r["rmse_mean"], ".2f"), _fmt(r["rmse_median"], ".2f"),
             _fmt(r["bias_mean_per_series"], ".2f")] for _, r in main.iterrows()]
    out += ["### Bias and per-series error, main table (bias = actual - forecast, positive = under-forecast)",
            md_table(header, rows), ""]

    # Category level
    header = ["Model", *cut_labels, "Mean"]
    rows = []
    for _, r in main[main["family"] != "Baseline"].iterrows():
        vals = per_window(cat_long, r["model"], "wape_pct")
        rows.append([r["model"], *[f"{v:.1f}" for v in vals], f"{r['cat_wape_mean']:.1f}"])
    out += ["### Category x location portfolio WAPE (%), same predictions summed up", md_table(header, rows), ""]

    # Appendix: every committed configuration
    header = ["Model", "Target", "Windows", *cut_labels, "Mean", "Wins", "Bias %", "RMSE mean"]
    rows = []
    for _, r in summary[summary["family"] != "Baseline"].sort_values(["family", "wape_mean"]).iterrows():
        vals = per_window(sku_long, r["model"], "wape_pct")
        rows.append([r["model"], r["target"], r["window_def"].split(" ")[0], *[f"{v:.1f}" for v in vals],
                     f"{r['wape_mean']:.1f}", f"{r['windows_beating_baseline']}/4", f"{r['bias_pct_mean']:.1f}",
                     f"{r['rmse_mean']:.2f}"])
    out += ["### Appendix: every committed configuration (SKU x location WAPE %)", md_table(header, rows), ""]

    # Data behaviour
    header = ["Window (cutoff)", "Peak?", "Actual units", "Units / series", "Series with zero sales (%)",
              "Poisson-expected zeros (%)", "Poisson noise-floor WAPE (%)"]
    rows = [[pd.Timestamp(r["cutoff"]).strftime("%Y-%m-%d"), "yes" if r["is_peak_window"] else "no",
             f"{r['actual_total']:,.0f}", f"{r['mean_actual_per_series']:.2f}", f"{r['observed_pct_zero']:.1f}",
             f"{r['poisson_pct_zero']:.1f}", f"{r['poisson_floor_wape_pct']:.1f}"] for _, r in evidence.iterrows()]
    out += ["### Data behaviour per window", md_table(header, rows), ""]

    # Forecast mass on zero-actual series (main table only)
    header = ["Model", *[f"{lbl}" for lbl in cut_labels]]
    rows = []
    for _, r in main[main["family"] != "Baseline"].iterrows():
        sub = mass_long[mass_long["model"] == r["model"]].set_index("cutoff")
        rows.append([r["model"], *[f"{sub.loc[c, 'forecast_on_zero_series']:,.0f}" for c in cutoffs]])
    out += ["### Forecast units placed on series that sold nothing in the window", md_table(header, rows), ""]

    # Scoring-convention sensitivity: same predictions, scored on actual > 0 rows only (the baseline's convention)
    base_wape = sku_long[sku_long["model"] == BASELINE_NAME].set_index("cutoff")["wape_pct"]
    header = ["Model", *[f"{lbl}" for lbl in cut_labels], "Champion (committed)"]
    rows = []
    for _, r in main[main["family"] != "Baseline"].iterrows():
        sub = sensitivity[sensitivity["model"] == r["model"]].set_index("cutoff")["wape_actual_positive_only"]
        rows.append([r["model"], *[f"{sub[c]:.1f}" for c in cutoffs], ""])
    rows.append([BASELINE_NAME, *[f"{base_wape[c]:.1f}" for c in cutoffs], "as committed"])
    out += ["### Sensitivity: WAPE (%) if models are scored on series with actual > 0 only (the baseline's convention)",
            md_table(header, rows), ""]
    return "\n".join(out)


# %%
if __name__ == "__main__":
    sku_long, cat_long, mass_long, summary, windows, flags = score_all()
    summary = mark_main_table(summary)

    # Data-behaviour evidence uses an exact-window run's actuals (XGBoost) so it matches the baseline's windows.
    evidence = poisson_noise_floor(windows["XGBoost v1"]).merge(flags, on="cutoff")

    sku_long.to_csv(OUTPUT_DIR / "comparison_sku_portfolio.csv", index=False)
    cat_long.to_csv(OUTPUT_DIR / "comparison_category_portfolio.csv", index=False)
    mass_long.to_csv(OUTPUT_DIR / "zero_actual_forecast_mass.csv", index=False)
    summary.to_csv(OUTPUT_DIR / "comparison_summary.csv", index=False)
    evidence.to_csv(OUTPUT_DIR / "data_behavior_evidence.csv", index=False)
    sensitivity = convention_sensitivity(windows)
    sensitivity.to_csv(OUTPUT_DIR / "convention_sensitivity.csv", index=False)

    tables = build_report_tables(sku_long, cat_long, summary, evidence, mass_long, sensitivity)
    (OUTPUT_DIR / "report_tables.md").write_text(tables, encoding="utf-8")
    print(tables)
    print(f"\nWrote CSVs and report_tables.md to {OUTPUT_DIR}")
