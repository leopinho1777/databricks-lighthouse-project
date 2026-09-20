# Prophet (task 3.4)

One Prophet model **per** (`product_variant_id`, `location_id`) series, scored under the shared Stage 3
protocol (`../_shared/evaluate.py`) and logged to the `/Shared/02_model_comparison` MLflow experiment. Five
configurations are run, each over the full 6,054-series catalog and four rolling-origin cutoffs (24,216 fits).

**Result:** no configuration beats the `seasonal_naive_genuine_91d_v2` champion in any window (0 of 20 window
comparisons). Two questions this experiment answers cleanly: Brazilian holidays add nothing for this catalog,
and a rigid trend (changepoint prior 0.01) is the best of the three trend settings tested on the two off-peak
windows. Multiplicative seasonality on the log1p target is unstable and is not used.

## Hypotheses

The tracker justifies Prophet as "purpose-built for seasonal, holiday-driven time series like this one". The five
runs test that justification and the trend assumption directly:

- `prophet_no_holidays` isolates whether Brazilian holidays help once yearly seasonality is in the model.
- `prophet_changepoint_flexible` / `_rigid` check Prophet's trend component against the project's smooth
  ~14–17%/year growth (`10_feature_engineering/10_frozen_feature_set.md`).
- `prophet_seasonality_multiplicative` checks the seasonality mode on a log1p target.

## Design

- **Per-series fit.** Unlike Random Forest, which fits one pooled model, Prophet handles one series at a
  time, so cost is dominated by cmdstanpy's fixed per-`.fit()` overhead × series count. The timing pilot
  (`pilot_timing.py`) measures it before any run and decides between the full catalog and a stratified
  subsample; `train_prophet.py` refuses to start without the pilot's decision file.
- **Grain and target.** Weekly panel (`load_weekly_panel()`), target `log1p(qty_sold_net)` back-transformed with
  `expm1().clip(lower=0)`, the same convention as Random Forest. `weekly_seasonality=False` (the panel is
  already weekly, so there is no sub-weekly cycle) and `yearly_seasonality=True` set explicitly, because
  `"auto"` silently disables yearly seasonality below about two full cycles of history and per-series history
  length varies a lot.
- **Frozen feature set.** Calendar is Prophet's own yearly seasonality (plus Brazilian holidays in every run
  except `prophet_no_holidays`); trend is Prophet's changepoint-driven trend. No other inputs.
- **Primary tuned parameter:** `changepoint_prior_scale` (0.05 default, 0.5 flexible, 0.01 rigid).
- **Cold start.** A series with fewer than `MIN_TRAIN_POINTS = 10` weekly observations (about 2.5 months), or any
  other per-series fit failure, forecasts 0. The threshold is not derived from this catalog's history depths;
  the pilot and every run report the fallback rate, which is 0 on every cutoff, so it never triggers.
- **Window alignment.** Same straddle-week handling as Random Forest (train weeks ≤ cutoff − 6 days; the scored
  horizon starts at the first Monday after the cutoff). The `actual_total` per window is therefore
  45,341 / 21,902 / 18,688 / 42,035 units, up to 9.49% away from the baseline's on 2025-07-01; the cause and
  decomposition are in `../eros_randomforest/README.md` ("Actual demand versus the baseline"). Read the
  2025-07-01 window with reduced confidence.
- **Efficiency.** Each cutoff's training frame is grouped once by `(product_variant_id, location_id)` and series
  are fetched with `.get_group()`. A boolean-mask filter per series would scan the ~2.1M-row panel 24,216
  times, which costs about as much as the fits themselves.
- **Artifacts.** One model and one plot per run: the exemplar series' final-cutoff fit and its trend/seasonality
  decomposition (`<run>_exemplar_decomposition.png`). The exemplar is the highest-volume series in the training
  window at the last cutoff, `product_variant_id=448`, `location_id=3` (194 units), the same series in every run.
  Per-segment RMSE/bias are reported with std/min/max because Lumpy is the highest-variance segment.

## Running it

```bash
uv sync --dev --group forecasting
# One-time CmdStan backend (the Python packages alone are not enough), see "CmdStan setup" below
uv run python forecasting/experiments/eros_prophet/pilot_timing.py     # writes output/timing_pilot_*.csv
uv run python forecasting/experiments/eros_prophet/train_prophet.py    # all five configs (add run names to subset)
```

`train_prophet.py --full-catalog <run_name>` forces the full catalog for one configuration when the pilot's
decision is `stratified_subsample`. The committed decision is `full_catalog`.

**Timing pilot.** 209 series (194 Intermittent + 15 Lumpy, stratified from
`04_demand_classification/output/demand_classification.csv`, `random_state=42`), timed at the 2025-09-30
cutoff: mean 0.158 s per fit + predict (median 0.157, max 0.241), 0 cold-start fallbacks, Lumpy fit-time std
0.004 s. Threshold for the full catalog is 0.223 s per fit (90 minutes per configuration), so the decision is
`full_catalog`. Extrapolated cost: 1.06 h per configuration. With the current code a configuration takes about 1–1.4 hours
(59–84 minutes measured across four of the five runs); the pilot times series selection and fit + predict, not
output assembly.

**CmdStan setup (Windows).** `uv sync` installs `prophet` and `cmdstanpy` but not the CmdStan binaries. Run the
RTools40 installer directly rather than through cmdstanpy (its own launch of the installer fails from a
Bash-style shell): download `RTools40.exe`, then in PowerShell run it with
`Start-Process ... /SP- /SILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR="<home>\.cmdstan\RTools40" /NOICONS /NORESTART`.
Install `mingw32-make` from the RTools MSYS environment (`pacman -Sy mingw-w64-x86_64-make --noconfirm`, with
`RTools40\usr\bin` first on `PATH`), then run `python -m cmdstanpy.install_cmdstan --compiler`. Always pass
`--compiler`: it puts the toolchain on `PATH` in the same process before `make build` runs.

Data snapshot: runs 1–4 read Delta version 4 (2026-09-11 19:44:50); `prophet_no_holidays` read Delta version 6
(2026-09-18 19:53:46). The scratch table changed between them (cause not tracked), but `actual_total` per cutoff is
identical in all five runs, so the numbers this experiment depends on are unchanged.

| Run | MLflow |
|---|---|
| `prophet_baseline` | [30246275…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/30246275252a4c6fbb0ffce23b9355dc) |
| `prophet_changepoint_flexible` | [5d879919…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/5d879919f0f544ab812dc4f2879087e2) |
| `prophet_changepoint_rigid` | [5a8b736b…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/5a8b736b21754713b1df27c95669d148) |
| `prophet_seasonality_multiplicative` | [f057abd5…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/f057abd52dc1401493326ba2293ee262) |
| `prophet_no_holidays` | [e1c8fe0f…](https://dbc-fc67e327-d40e.cloud.databricks.com/ml/experiments/3452649495455705/runs/e1c8fe0f56e342c9a5f7348e130388df) |

## Results

Portfolio WAPE (%) at SKU × location, all 6,054 series (lower is better):

| Configuration | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Beats champion |
|---|---|---|---|---|---|
| `prophet_baseline` (prior 0.05, additive, holidays on) | 86.98 | 102.78 | 106.28 | 88.76 | 0/4 |
| `prophet_changepoint_flexible` (prior 0.5) | 87.21 | 105.56 | 108.24 | 88.78 | 0/4 |
| `prophet_changepoint_rigid` (prior 0.01) | 87.45 | **102.22** | **104.74** | 89.46 | 0/4 |
| `prophet_seasonality_multiplicative` | 93.09 | 105.63 | 111.08 | 91.74 | 0/4 |
| `prophet_no_holidays` | 87.02 | 102.64 | 106.06 | **88.64** | 0/4 |
| Champion (`seasonal_naive_genuine_91d_v2`) | 78.84 | 84.43 | 88.05 | 79.89 | n/a |

Per-segment RMSE and bias (mean across series; bias = actual − forecast, positive means under-forecast):

| Configuration | Intermittent RMSE / bias | Lumpy RMSE / bias | Worst-series RMSE (Intermittent) |
|---|---|---|---|
| `baseline` | 6.42 / 3.51 | 5.13 / 2.53 | 24.51 |
| `changepoint_flexible` | 6.45 / 3.29 | 5.13 / 2.27 | 23.28 |
| `changepoint_rigid` | 6.47 / 3.70 | 5.15 / 2.69 | 24.40 |
| `seasonality_multiplicative` | 6.70 / 2.98 | 5.44 / 1.96 | **114.44** |
| `no_holidays` | 6.41 / 3.53 | 5.13 / 2.56 | 24.40 |

## Interpretation

- **Holidays do not matter for this catalog.** `prophet_no_holidays` is within 0.22 pp of `prophet_baseline` on
  every window (0.04 / 0.14 / 0.22 / 0.12) and its per-segment RMSE matches to two decimals. This confirms
  `10_feature_engineering`'s finding that holidays contribute about 0% in a pooled linear panel regression, with a
  different model class and method. Holidays add per-fit setup cost and no
  measurable accuracy.
- **The trend setting matters little, and less than the gap to seasonal naive.** The rigid trend (0.01) is the
  best of the three on the two off-peak windows (102.22 / 104.74 against 102.78 / 106.28 at the default and
  105.56 / 108.24 at 0.5), consistent with this catalog's smooth growth rewarding a trend that does not chase
  noise. On the two peak windows the three settings are within 0.7 pp of each other and the ordering flips.
  Segment RMSE moves the opposite way (rigid is marginally worst), so portfolio WAPE and per-series RMSE do not
  agree on the best setting.
- **Multiplicative seasonality is unstable on this target.** It is the worst configuration on every window, with
  a worst-series RMSE of 114.44 against 24.51 and a worst bias of −55.14 against −3.52. Multiplicative mode
  scales seasonality by the trend, and on a log1p-transformed target the trend sits close to zero for
  low-volume series (96.8% of the catalog), so the scaling blows up. The additive mode is used everywhere else.
- **Systematic under-forecast.** All configurations have positive mean bias. The log1p target makes forecasts
  conditional medians, which for a mostly-zero series are close to zero; the same effect appears in the other
  log-target experiments (`../../11_model_comparison`).

## Limitations and next steps

- The trend axis has only three points (0.01, 0.05, 0.5). A value below 0.01 (0.001–0.005) is untested and
  would show whether the improvement continues or reverses.
- The worst-series blow-up under multiplicative seasonality is worth tracing series by series
  (`prophet_seasonality_multiplicative_window_totals.csv`), which would also identify the low-volume series
  that stress any multiplicative model.
- Peak-season metrics are logged every run but are only informally comparable with the baseline's peak-season row
  (RMSE and bias, no WAPE per window).
- Fitting Prophet on a mean-targeting basis (raw counts or a bias correction) is not tested here; it is the
  most direct way to address the under-forecast.
