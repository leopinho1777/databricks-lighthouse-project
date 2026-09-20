# Stage 3 — Model comparison experiments

Stage 3 is the Action Plan's third phase (tasks 3.n, model comparison). Folder numbers under `forecasting/`
(`01`–`11`) track the order deliverables were produced; Stage/Phase numbers track the Action Plan's sections, so
the two do not line up: folder `09` closes Phase 1, folder `10` is Stage 2, and folder `11` closes Stage 3.

One folder per person per model: `experiments/<name>_<model>/`. Code stays isolated so people do not collide on
files, and results are logged to the same shared MLflow experiment (`/Shared/02_model_comparison`) so the
comparison stays in one place. The finished comparison of every experiment is in
[`../11_model_comparison/11_model_comparison_report.md`](../11_model_comparison/11_model_comparison_report.md).

## Experiments

| Folder | Model (task) | Configurations | Fit grain | Target | Champion beaten in |
|---|---|---|---|---|---|
| [`eva_regression/`](eva_regression/README.md) | Fixed-effects panel regression (3.1) | 2 (uncorrected, Duan smearing) | weekly, prorated by day | log1p | 1 of 8 windows |
| [`eros_randomforest/`](eros_randomforest/README.md) | Random Forest (3.2) | 5 | weekly | log1p | 0 of 20 |
| [`gabriel_xgboost/`](gabriel_xgboost/README.md) | XGBoost + Hyperopt (3.3) | 1 (tuned) | daily, single-shot 91-day target | raw counts | 1 of 4 |
| [`eros_prophet/`](eros_prophet/README.md) | Prophet (3.4) | 5 | weekly, one model per series | log1p | 0 of 20 |
| [`pinho_sarima/`](pinho_sarima/README.md) | SARIMA benchmark (3.5) | 2 | weekly, one model per series | log1p | 0 of 8 |

Each folder's `README.md` documents the design, how to run it, the results and the limitations. Every experiment
writes `<run>_window_totals.csv` (one row per series × cutoff with the summed `actual` and `pred`), which is the
input to the cross-model comparison.

## The evaluation protocol

`_shared/evaluate.py` is the protocol in code; its module docstring carries the rationale. Every model is scored
on the **total demand over a 91-day window per (`product_variant_id`, `location_id`)**, across the same four
rolling origins used by the Phase 1 baseline (2024-12-31, 2025-04-01, 2025-07-01, 2025-09-30, from
`../09_baseline_close_out/walk_forward.py`), against the `seasonal_naive_genuine_91d_v2` champion in
`/Shared/00_baseline`. It reports RMSE and bias per series across the four windows and portfolio WAPE per
window, at two levels: SKU × location (`evaluate()`) and category × location (`to_category_level()`, which sums
the *same* window totals rather than re-forecasting). MAPE/sMAPE are excluded because `05_croston_sba` shows they
are structurally uninformative on this catalog.

Fit at whatever grain suits the model, weekly or daily, and sum the predictions into the window before scoring;
that is what makes results comparable without forcing one modeling grain. Training uses data up to each cutoff
only, and a model that can be refit cheaply is refit per window. Why the forecast is held static for the whole
window (a forecast that is recomputed as time passes would see real actuals from inside the window it is scored
on) is explained in `../09_baseline_close_out/09_baseline_close_out_summary.md`.

**Conventions that affect how numbers compare** (all documented per experiment and in the comparison report):

- **Baseline coverage.** The champion's committed WAPE counts only series with sales in the window;
  `evaluate()` scores all 6,054 series, so a model is also charged for forecast placed on series that sold
  nothing (25–59% of series per window). The two are not on identical coverage; the comparison report shows the
  sensitivity.
- **Window definition.** Weekly-grain experiments (Random Forest, Prophet, SARIMA) exclude the Monday-anchored
  week that straddles a cutoff from both training and scoring, so their scored window is shifted by up to about 5
  days and `actual_total` differs from the baseline's (up to 9.49% on 2025-07-01). The panel regression prorates
  weeks by day and XGBoost uses exact windows, so their totals track the baseline's within 0.5–1.7%.
  `compare_to_baseline()` warns when `actual_total` drifts more than 0.5%.
- **Refit per window.** Random Forest, Prophet, SARIMA and the panel regression refit at every cutoff. XGBoost
  fits one model on origins up to 2024-12-31 and applies it at all four cutoffs (see its README).
- **Target.** Four families fit `log1p(qty)`, which yields a conditional median and under-forecasts a mostly-zero
  catalog; XGBoost fits raw counts, and the smearing run corrects the log target's retransformation bias.

## Using the protocol

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
from evaluate import compare_to_baseline, evaluate, get_cutoffs, to_category_level
```

Import it as a module, not as a package: the repo has three directories named `_shared`, and importing by
package name resolves to whichever one Python saw first.

Build one row per series per window, with actual and predicted already summed:

| product_variant_id | location_id | cutoff     | actual | pred |
| ------------------ | ----------- | ---------- | ------ | ---- |
| 1042               | 3           | 2024-12-31 | 17     | 12.4 |
| 1042               | 3           | 2025-04-01 | 9      | 11.8 |

```python
results = evaluate(window_totals)              # SKU x location
results["portfolio"]                           # one row per window
results["per_series_summary"]                  # RMSE/bias across the 4 windows

print(compare_to_baseline(results["portfolio"]))   # vs. the champion, per window

by_category = evaluate(
    to_category_level(window_totals), keys=["category_name", "location_id"]
)
```

`compare_to_baseline()` also warns if the model's `actual_total` per window differs from the baseline's by more
than 0.5%, which signals that the window definition or the source filter diverged and the WAPE comparison is not
like for like.

`_shared/repro.py` provides `get_table_version()` and `get_library_versions()` for the MLflow reproducibility tags
every experiment logs (Delta snapshot of the input table and library versions).

## Adding an experiment

1. Create `experiments/<name>_<model>/` with the training script, an `output/` folder, and a `README.md` covering
   purpose, design, how to run, results and limitations (the five existing READMEs are the template).
2. Read inputs from the shared prod marts for reference data and from your own scratch schema for
   `fact_demand_daily` (`../README.md`, "Data source convention"), and take the frozen feature set from
   `../10_feature_engineering/10_frozen_feature_set.md`.
3. Score through `_shared/evaluate.py`, log to `/Shared/02_model_comparison`, and write `<run>_window_totals.csv`.
4. Register the new runs in `../11_model_comparison/build_comparison.py` (`RUNS`) and re-run it.

Everything else is the experiment's own: features, model, tuning, and how it splits data inside the training
window. Only the scoring is shared, so no model's result is measured differently from another's.
