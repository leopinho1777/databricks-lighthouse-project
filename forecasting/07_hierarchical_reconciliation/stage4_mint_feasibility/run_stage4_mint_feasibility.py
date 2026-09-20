# %% [markdown]
# # Hierarchical reconciliation — Stage 4: MinT feasibility check
#
# Validates whether MinT reconciliation is applicable *before* attempting it,
# per the reconciliation context document's Section 3 feasibility gate:
#
# 1. Enough historical (holdout) periods exist per series to estimate a
#    stable error-covariance matrix.
# 2. Base forecasts from both Bottom-Up (Stage 1) and Top-Down (Stage 2) are
#    already validated (Stages 1-3 — done).
# 3. The covariance estimate is numerically stable (not near-singular given
#    the number of series relative to the number of holdout observations).
#
# If any check fails, this stage stops and reports rather than forcing a
# MinT implementation on an unstable covariance estimate. See
# `output/mint_feasibility_check.md` for the write-up; this script produces
# the numbers behind it. Per `pyproject.toml`'s `forecasting` dependency
# group (numpy/pandas/databricks-sql-connector only, no scipy), the
# covariance/rank/condition-number work below uses `numpy.linalg` only, per
# the plan's own housekeeping note.

# %%
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

NATIONAL_FORECASTS = Path(__file__).resolve().parents[1] / "stage2_top_down" / "output" / "_national_forecasts.parquet"
NATIONAL_CLASSIFICATION = Path(__file__).resolve().parents[1] / "stage2_top_down" / "output" / "national_classification.csv"
RECOMMENDED_FORECASTS = Path(__file__).resolve().parents[2] / "06_multi_grain" / "output" / "_recommended_forecasts.parquet"

HOLDOUT_YEAR = 2025  # matches most_recent_complete_year() across every prior stage

# %% [markdown]
# ## 1. Build the base-forecast error matrix at each hierarchy level:
# rows = holdout day, columns = series, values = actual - forecast (Stage
# 2's routed national forecast for the "national" level, Stage 1/`06`'s
# recommended per-series forecast for the "location" level). Reused directly
# from each stage's own cached output, no new forecasting logic.

# %%
def national_error_matrix() -> pd.DataFrame:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2_top_down"))
    from run_stage2_top_down import route_forecast

    forecasted = pd.read_parquet(NATIONAL_FORECASTS)
    classification = pd.read_csv(NATIONAL_CLASSIFICATION, dtype={"product_variant_id": str})[["product_variant_id", "category"]]
    forecasted = forecasted.merge(classification, on="product_variant_id", how="left")
    forecasted["top_down_pred"] = [
        route_forecast(cat, ma, sba) for cat, ma, sba in zip(forecasted["category"], forecasted["ma_pred"], forecasted["sba_pred"])
    ]
    holdout = forecasted[forecasted["period"].dt.year == HOLDOUT_YEAR].copy()
    holdout["error"] = holdout["qty_sold_net"] - holdout["top_down_pred"]
    matrix = holdout.pivot(index="period", columns="product_variant_id", values="error")
    return matrix


def location_error_matrix() -> pd.DataFrame:
    recommended = pd.read_parquet(RECOMMENDED_FORECASTS)
    holdout = recommended[recommended["period"].dt.year == HOLDOUT_YEAR].copy()
    holdout["series_id"] = holdout["product_variant_id"] + "_" + holdout["location_id"]
    holdout["error"] = holdout["qty_sold_net"] - holdout["recommended_pred"]
    matrix = holdout.pivot(index="period", columns="series_id", values="error")
    return matrix


# %% [markdown]
# ## 2. Feasibility check 1 — holdout periods vs. rule-of-thumb requirement
# (3-5x the number of series being reconciled at that level).

# %%
def check_period_sufficiency(n_obs: int, n_series: int, level: str) -> dict:
    required_min, required_max = 3 * n_series, 5 * n_series
    return {
        "level": level,
        "n_series": n_series,
        "n_holdout_obs": n_obs,
        "required_min_obs_3x": required_min,
        "required_max_obs_5x": required_max,
        "ratio_actual_to_required_min": round(n_obs / required_min, 3),
        "sufficient": n_obs >= required_min,
    }


# %% [markdown]
# ## 3. Feasibility check 3 — numerical stability of the covariance estimate.
# Rather than forming the full (n_series x n_series) covariance matrix
# directly (6,054² ≈ 293MB and an expensive SVD), the covariance matrix's
# nonzero eigenvalues are exactly the squared singular values of the cheaper
# (n_obs x n_series) error matrix — computed via its economy SVD instead.
# A sample covariance matrix from `n_obs` observations has rank at most
# `n_obs - 1` by construction, regardless of `n_series` — this check
# confirms that analytic fact empirically and quantifies how singular the
# result is.

# %%
def check_covariance_stability(error_matrix: pd.DataFrame, level: str) -> dict:
    values = error_matrix.to_numpy()
    n_obs, n_series = values.shape
    # de-mean per series (sample covariance convention), then take the
    # economy SVD of the (n_obs x n_series) matrix directly.
    centered = values - values.mean(axis=0, keepdims=True)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    eigenvalues = singular_values**2 / (n_obs - 1)  # eigenvalues of the (n_series x n_series) covariance matrix

    max_rank = min(n_obs - 1, n_series)
    tol = eigenvalues.max() * n_series * np.finfo(float).eps
    effective_rank = int((eigenvalues > tol).sum())

    smallest_nonzero = eigenvalues[eigenvalues > tol].min() if effective_rank else np.nan
    condition_number = eigenvalues.max() / smallest_nonzero if effective_rank else np.inf

    return {
        "level": level,
        "n_series": n_series,
        "n_obs": n_obs,
        "max_possible_rank_from_n_obs": max_rank,
        "effective_rank": effective_rank,
        "n_singular_zero_eigenvalues": n_series - effective_rank,
        "pct_series_with_zero_eigenvalue": round(100 * (n_series - effective_rank) / n_series, 1),
        "largest_eigenvalue": float(eigenvalues.max()),
        "smallest_nonzero_eigenvalue": float(smallest_nonzero) if effective_rank else np.nan,
        "condition_number": float(condition_number),
        "numerically_stable": bool(effective_rank == n_series and condition_number < 1e10),
    }


# %%
if __name__ == "__main__":
    print("Building national-level error matrix (1,009 products)...")
    national_errors = national_error_matrix()
    print(f"  shape: {national_errors.shape}")

    print("Building location-level error matrix (6,054 product x location series)...")
    location_errors = location_error_matrix()
    print(f"  shape: {location_errors.shape}")

    # --- check 1: period sufficiency ---
    period_checks = pd.DataFrame(
        [
            check_period_sufficiency(national_errors.shape[0], national_errors.shape[1], "national"),
            check_period_sufficiency(location_errors.shape[0], location_errors.shape[1], "location"),
        ]
    )
    period_checks.to_csv(OUTPUT_DIR / "period_sufficiency_check.csv", index=False)
    print("\n=== Check 1: holdout period sufficiency ===")
    print(period_checks.to_string(index=False))

    # --- check 3: covariance numerical stability ---
    print("\nComputing national-level covariance eigenspectrum (SVD)...")
    national_stability = check_covariance_stability(national_errors, "national")
    print("Computing location-level covariance eigenspectrum (SVD)...")
    location_stability = check_covariance_stability(location_errors, "location")

    stability_checks = pd.DataFrame([national_stability, location_stability])
    stability_checks.to_csv(OUTPUT_DIR / "covariance_stability_check.csv", index=False)
    print("\n=== Check 3: covariance numerical stability ===")
    print(stability_checks.to_string(index=False))

    feasible = bool(period_checks["sufficient"].all() and stability_checks["numerically_stable"].all())
    print(f"\n=== MinT feasible: {feasible} ===")
