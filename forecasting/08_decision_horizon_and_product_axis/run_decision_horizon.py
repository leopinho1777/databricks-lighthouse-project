# %% [markdown]
# # Decision-horizon evaluation and product-axis aggregation (Stage 08)
#
# Three tests layered on `04`-`07`: ADI/CV² classification at monthly grain and
# along the product axis; error measured over the client's decision horizon
# (15/30 days) instead of per day; and aggregate-then-disaggregate versus direct
# per-SKU forecasting. See `08_decision_horizon_summary.md` for the write-up;
# this script produces the numbers behind it.
#
# Reads `fct_sales` directly rather than `02`'s `fact_demand_daily` prototype,
# so it has no dependency on another developer's scratch schema -- reads the
# stable prod marts instead (see `_shared/db_connection.py`'s data source
# convention). That means gross quantity here versus net there — the
# calibration checks printed at the end quantify the difference (~0.2%).

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from _shared.db_connection import PROD_MARTS, query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MARTS = PROD_MARTS
HOLDOUT_START, HOLDOUT_END = "2025-01-01", "2025-12-31"  # same holdout as 03-07
ADI_THRESHOLD, CV2_THRESHOLD = 1.32, 0.49                # Syntetos & Boylan (2005), as in 04
MA_WINDOW = 28                                           # same moving average as 03

# Temp views do not survive between calls (query_df opens one connection per
# query), so every shared block below is a CTE injected into each statement.
SALES = f"""
vendas AS (
    SELECT s.product_variant_id,
           s.location_id,
           p.product_id,
           COALESCE(p.category_name, 'Uncategorised') AS category_name,
           s.placed_at,
           s.quantity
    FROM {MARTS}.fct_sales AS s
    LEFT JOIN {MARTS}.dim_products AS p
           ON s.product_variant_id = p.product_variant_id
    WHERE s.order_status IN ('paid', 'confirmed')
)"""

CAL = f"""
cal AS (
    SELECT date_day AS dia
    FROM {MARTS}.dim_calendary
    WHERE date_day BETWEEN (SELECT MIN(DATE(placed_at)) FROM vendas)
                       AND (SELECT MAX(DATE(placed_at)) FROM vendas)
)"""

def dense_cte(keys, prefix, with_seasonal_naive=True):
    """Dense daily series for one level, plus its 28-day moving average.

    No lookahead: the window ends at `1 PRECEDING`. Seasonal naive joins on the
    real calendar date one year earlier (same leap-year reasoning as 03).
    """
    k = ", ".join(keys)
    on_actuals = " AND ".join(f"g.{c} <=> r.{c}" for c in keys)
    on_lastyear = " AND ".join(f"a.{c} <=> b.{c}" for c in keys)
    block = f"""
{prefix}pairs AS (SELECT DISTINCT {k} FROM vendas),
{prefix}actuals AS (
    SELECT {k}, DATE(placed_at) AS dia, SUM(quantity) AS q
    FROM vendas GROUP BY {k}, DATE(placed_at)
),
{prefix}dense AS (
    SELECT g.*, COALESCE(r.q, 0) AS q
    FROM (SELECT p.*, c.dia FROM {prefix}pairs p CROSS JOIN cal c) g
    LEFT JOIN {prefix}actuals r ON {on_actuals} AND g.dia = r.dia
),
{prefix}ma AS (
    SELECT d.*,
           AVG(q) OVER (PARTITION BY {k} ORDER BY dia
                        ROWS BETWEEN {MA_WINDOW} PRECEDING AND 1 PRECEDING) AS ma28
    FROM {prefix}dense d
)"""
    if with_seasonal_naive:
        block += f""",
{prefix}series AS (
    SELECT a.*, b.q AS sn
    FROM {prefix}ma a
    LEFT JOIN {prefix}dense b ON {on_lastyear} AND b.dia = ADD_MONTHS(a.dia, -12)
)"""
    else:
        block += f""",
{prefix}series AS (SELECT * FROM {prefix}ma)"""
    return block

# %% [markdown]
# ## 1. Demand-pattern classification by grain and level
#
# Same ADI/CV² definitions and thresholds as `04`, including the left-trim to
# each series' own first non-zero period. Adds monthly grain and the product
# axis, neither covered by `04` (daily) or `06` (weekly).

# %%
def classification_sql(keys, grain):
    k = ", ".join(keys)
    return f"""
WITH {SALES},
per_period AS (
    SELECT {k}, DATE_TRUNC('{grain}', placed_at) AS periodo, SUM(quantity) AS q
    FROM vendas GROUP BY {k}, DATE_TRUNC('{grain}', placed_at)
),
periods AS (SELECT DISTINCT periodo FROM per_period),
numbered AS (
    SELECT periodo,
           ROW_NUMBER() OVER (ORDER BY periodo) AS idx,
           COUNT(*) OVER ()                     AS total_periods
    FROM periods
),
summary AS (
    SELECT {k},
           MIN(periodo)   AS first_period,
           COUNT(*)       AS sale_periods,
           AVG(q)         AS mean_size,
           STDDEV_SAMP(q) AS sd_size
    FROM per_period GROUP BY {k}
),
stats AS (
    SELECT s.sale_periods,
           (n.total_periods - n.idx + 1) / s.sale_periods AS adi,
           POW(s.sd_size / s.mean_size, 2)                AS cv2
    FROM summary s JOIN numbered n ON n.periodo = s.first_period
)
SELECT CASE WHEN sale_periods < 2                                         THEN 'insufficient_data'
            WHEN adi <  {ADI_THRESHOLD} AND cv2 <  {CV2_THRESHOLD}        THEN 'smooth'
            WHEN adi >= {ADI_THRESHOLD} AND cv2 <  {CV2_THRESHOLD}        THEN 'intermittent'
            WHEN adi <  {ADI_THRESHOLD} AND cv2 >= {CV2_THRESHOLD}        THEN 'erratic'
            ELSE 'lumpy' END                     AS pattern,
       COUNT(*)                                  AS n_series,
       PERCENTILE_APPROX(adi, 0.5)               AS adi_median,
       PERCENTILE_APPROX(cv2, 0.5)               AS cv2_median
FROM stats GROUP BY 1
"""

CLASSIFICATION_LEVELS = [
    ("SKU x location",      ["product_variant_id", "location_id"], "DAY"),
    ("SKU x location",      ["product_variant_id", "location_id"], "WEEK"),
    ("SKU x location",      ["product_variant_id", "location_id"], "MONTH"),
    ("Category x location", ["category_name", "location_id"],      "WEEK"),
    ("Category x location", ["category_name", "location_id"],      "MONTH"),
]

frames = []
for level, keys, grain in CLASSIFICATION_LEVELS:
    df = query_df(classification_sql(keys, grain))
    df.insert(0, "grain", grain.lower())
    df.insert(0, "level", level)
    df["pct"] = (100 * df["n_series"] / df["n_series"].sum()).round(1)
    frames.append(df)

classification = pd.concat(frames, ignore_index=True)
classification.to_csv(OUTPUT_DIR / "demand_classification_by_grain.csv", index=False)
print("\n=== 1. Demand-pattern classification ===")
print(classification.to_string(index=False))

# %% [markdown]
# ## 2. Error over the decision horizon (1 / 15 / 30 days)
#
# Actuals and forecasts are summed inside non-overlapping windows before the
# error is computed. WAPE is added because it is the only metric here that is
# comparable across hierarchy levels and stays defined with zero actuals.

# %%
def window_series_sql(keys, days):
    k = ", ".join(keys)
    bucket = f"FLOOR(DATEDIFF(dia, DATE'{HOLDOUT_START}') / {days})"
    return f"""
WITH {SALES},
{CAL},
{dense_cte(keys, "s_")},
holdout AS (
    SELECT {k}, {bucket} AS bucket, q, ma28, sn
    FROM s_series
    WHERE dia BETWEEN DATE'{HOLDOUT_START}' AND DATE'{HOLDOUT_END}'
),
sums AS (
    SELECT {k}, bucket, SUM(q) AS actual, SUM(ma28) AS f_ma, SUM(sn) AS f_sn
    FROM holdout GROUP BY {k}, bucket
    HAVING COUNT(*) = {days}
),
long AS (
    SELECT {k}, bucket, actual, 'moving_average' AS method, f_ma AS forecast FROM sums
    UNION ALL
    SELECT {k}, bucket, actual, 'seasonal_naive' AS method, f_sn AS forecast FROM sums
)
SELECT method,
       AVG(rmse)                                          AS rmse_series,
       AVG(bias)                                          AS bias_series,
       100 * SUM(abs_error) / NULLIF(SUM(actual_total), 0) AS wape_pct
       FROM (
    SELECT {k}, method,
           SQRT(AVG(POW(actual - forecast, 2))) AS rmse,
           AVG(actual - forecast)               AS bias,
           SUM(ABS(actual - forecast))          AS abs_error,
           SUM(actual)                          AS actual_total
    FROM long GROUP BY {k}, method
)
GROUP BY method
"""

def window_portfolio_sql(keys, days):
    """Sum every series per window first, then measure the error of the total."""
    k = ", ".join(keys)
    bucket = f"FLOOR(DATEDIFF(dia, DATE'{HOLDOUT_START}') / {days})"
    return f"""
WITH {SALES},
{CAL},
{dense_cte(keys, "s_")},
holdout AS (
    SELECT {k}, {bucket} AS bucket, q, ma28, sn
    FROM s_series
    WHERE dia BETWEEN DATE'{HOLDOUT_START}' AND DATE'{HOLDOUT_END}'
),
sums AS (
    SELECT {k}, bucket, SUM(q) AS actual, SUM(ma28) AS f_ma, SUM(sn) AS f_sn
    FROM holdout GROUP BY {k}, bucket
    HAVING COUNT(*) = {days}
),
totals AS (
    SELECT bucket, SUM(actual) AS actual, SUM(f_ma) AS f_ma, SUM(f_sn) AS f_sn
    FROM sums GROUP BY bucket
)
SELECT 'moving_average' AS method, SQRT(AVG(POW(actual - f_ma, 2))) AS rmse_portfolio FROM totals
UNION ALL
SELECT 'seasonal_naive' AS method, SQRT(AVG(POW(actual - f_sn, 2))) AS rmse_portfolio FROM totals
"""

WINDOW_LEVELS = [
    ("SKU x location",      ["product_variant_id", "location_id"]),
    ("Category x location", ["category_name", "location_id"]),
]

frames = []
for level, keys in WINDOW_LEVELS:
    for days in (1, 15, 30):
        metrics = query_df(window_series_sql(keys, days))
        portfolio = query_df(window_portfolio_sql(keys, days))
        merged = metrics.merge(portfolio, on="method")
        merged.insert(0, "window_days", days)
        merged.insert(0, "level", level)
        frames.append(merged)

window_metrics = pd.concat(frames, ignore_index=True).round(3)
window_metrics.to_csv(OUTPUT_DIR / "window_metrics_by_level.csv", index=False)
print("\n=== 2. Error over the decision horizon ===")
print(window_metrics.to_string(index=False))

# %% [markdown]
# ## 3. Aggregate-then-disaggregate versus direct per-SKU forecasting
#
# All three paths are evaluated at SKU x location, so no path is scored at an
# easier level. Disaggregation shares come from 2020-2024 only — using holdout
# data to build them would leak the answer into the test.

# %%
def paths_sql(days):
    # Qualified with s.: three dense series are joined below and all have `dia`.
    bucket = f"FLOOR(DATEDIFF(s.dia, DATE'{HOLDOUT_START}') / {days})"
    return f"""
WITH {SALES},
{CAL},
{dense_cte(["product_variant_id", "location_id"], "s_", with_seasonal_naive=False)},
{dense_cte(["category_name", "location_id"], "c_", with_seasonal_naive=False)},
{dense_cte(["product_id", "location_id"], "p_", with_seasonal_naive=False)},
variant_map AS (
    SELECT DISTINCT product_variant_id,
           product_id,
           COALESCE(category_name, 'Uncategorised') AS category_name
    FROM {MARTS}.dim_products
),
train AS (
    SELECT product_variant_id, location_id, SUM(q) AS q
    FROM s_series WHERE dia < DATE'{HOLDOUT_START}'
    GROUP BY product_variant_id, location_id
),
shares AS (
    SELECT t.product_variant_id, t.location_id, m.category_name, m.product_id,
           t.q / NULLIF(SUM(t.q) OVER (PARTITION BY m.category_name, t.location_id), 0) AS share_category,
           t.q / NULLIF(SUM(t.q) OVER (PARTITION BY m.product_id,    t.location_id), 0) AS share_product
    FROM train t JOIN variant_map m ON m.product_variant_id = t.product_variant_id
),
holdout AS (
    SELECT s.product_variant_id, s.location_id, {bucket} AS bucket, s.q,
           s.ma28                                                  AS f_direct,
           COALESCE(c.ma28, 0) * COALESCE(sh.share_category, 0)    AS f_category,
           COALESCE(p.ma28, 0) * COALESCE(sh.share_product, 0)     AS f_product
    FROM s_series s
    LEFT JOIN shares sh ON sh.product_variant_id = s.product_variant_id
                       AND sh.location_id        = s.location_id
    LEFT JOIN c_series c ON c.category_name = sh.category_name
                        AND c.location_id   = s.location_id AND c.dia = s.dia
    LEFT JOIN p_series p ON p.product_id    = sh.product_id
                        AND p.location_id   = s.location_id AND p.dia = s.dia
    WHERE s.dia BETWEEN DATE'{HOLDOUT_START}' AND DATE'{HOLDOUT_END}'
),
sums AS (
    SELECT product_variant_id, location_id, bucket,
           SUM(q) AS actual, SUM(f_direct) AS f_direct,
           SUM(f_category) AS f_category, SUM(f_product) AS f_product
    FROM holdout GROUP BY product_variant_id, location_id, bucket
    HAVING COUNT(*) = {days}
),
long AS (
    SELECT product_variant_id, location_id, bucket, actual, 'A_direct_per_sku' AS path, f_direct   AS forecast FROM sums
    UNION ALL
    SELECT product_variant_id, location_id, bucket, actual, 'B_via_category'   AS path, f_category AS forecast FROM sums
    UNION ALL
    SELECT product_variant_id, location_id, bucket, actual, 'C_via_product'    AS path, f_product  AS forecast FROM sums
),
per_series AS (
    SELECT product_variant_id, location_id, path,
           SQRT(AVG(POW(actual - forecast, 2))) AS rmse,
           AVG(actual - forecast)               AS bias,
           SUM(ABS(actual - forecast))          AS abs_error,
           SUM(actual)                          AS actual_total
    FROM long GROUP BY product_variant_id, location_id, path
),
portfolio AS (
    SELECT path, bucket, SUM(actual) AS actual, SUM(forecast) AS forecast
    FROM long GROUP BY path, bucket
)
SELECT s.path,
       AVG(s.rmse)                                              AS rmse_series,
       AVG(s.bias)                                              AS bias_series,
       100 * SUM(s.abs_error) / NULLIF(SUM(s.actual_total), 0)  AS wape_pct,
       MAX(p.rmse_portfolio)                                    AS rmse_portfolio
FROM per_series s
JOIN (
    SELECT path, SQRT(AVG(POW(actual - forecast, 2))) AS rmse_portfolio
    FROM portfolio GROUP BY path
) p ON p.path = s.path
GROUP BY s.path
"""

COVERAGE_SQL = f"""
WITH {SALES},
train AS (
    SELECT product_variant_id, location_id, SUM(quantity) AS q
    FROM vendas WHERE placed_at < DATE'{HOLDOUT_START}'
    GROUP BY product_variant_id, location_id
),
holdout AS (
    SELECT product_variant_id, location_id, SUM(quantity) AS q
    FROM vendas WHERE placed_at BETWEEN DATE'{HOLDOUT_START}' AND DATE'{HOLDOUT_END}'
    GROUP BY product_variant_id, location_id
)
SELECT COUNT(*)                                                          AS series_in_holdout,
       SUM(CASE WHEN t.q IS NULL THEN 1 ELSE 0 END)                      AS series_without_history,
       100 * SUM(CASE WHEN t.q IS NULL THEN h.q ELSE 0 END) / SUM(h.q)   AS pct_holdout_demand_affected
FROM holdout h
LEFT JOIN train t ON t.product_variant_id = h.product_variant_id
                 AND t.location_id        = h.location_id
"""

frames = []
for days in (1, 15, 30):
    df = query_df(paths_sql(days))
    df.insert(0, "window_days", days)
    frames.append(df)

paths = pd.concat(frames, ignore_index=True).round(3)
paths.to_csv(OUTPUT_DIR / "disaggregation_path_comparison.csv", index=False)

coverage = query_df(COVERAGE_SQL).round(2)
coverage.to_csv(OUTPUT_DIR / "share_coverage_check.csv", index=False)

print("\n=== 3. Disaggregation paths (all evaluated at SKU x location) ===")
print(paths.to_string(index=False))
print("\n=== Share coverage: series with no pre-holdout history ===")
print(coverage.to_string(index=False))