# Stage 3 — Model comparison experiments

"Stage 3" is the Action Plan's third phase (tasks 3.n — model comparison).
Folder numbers (`01`-`10`) track the order deliverables
were produced; Stage/Phase numbers track the Action Plan's four sections. The
two don't line up: folder `09` closes Phase 1, folder `10` is Stage 2.

One folder per person per model: `experiments/<name>_<model>/` (e.g.
`eva_xgboost/`). Code stays isolated so we don't collide on files; results are
logged to the same shared MLflow experiment so the comparison stays in one
place.

## The evaluation protocol

`_shared/evaluate.py` is the protocol in code — its module docstring carries
the full rationale and the team decision it came from. In short: every model
is scored on the **total demand over a 91-day window per
(product_variant_id, location_id)**, across the same four rolling origins the
Phase 1 close-out used, against the `seasonal_naive_genuine_91d_v2` champion.

Fit at whatever grain suits your model — weekly, daily — and sum your
predictions into the window before scoring. That is what makes results
comparable between us without forcing everyone onto the same modelling grain.

## Using it

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
from evaluate import compare_to_baseline, evaluate, get_cutoffs, to_category_level
```

Import as a module, not as a package: the repo already has two other
directories named `_shared`, and importing by package name resolves to
whichever one Python saw first.

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

`compare_to_baseline()` also warns if your `actual_total` per window differs
from the baseline's by more than 0.5% — that means the window definition or
the source filter diverged, and the WAPE comparison isn't meaningful.

Everything else is yours: features, model, tuning, how you split inside the
training window. Only the scoring is shared, so nobody's champion is measured
slightly differently from anyone else's.
