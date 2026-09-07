# %% [markdown]
# # Transformation layer exploration — demand forecasting Phase 1 / Task 1.1-1.5
#
# Runs every check backing `01_data_exploration_summary.md` against the live dev
# marts (`develop.eros_analytics_marts`). Re-run this after any dbt rebuild to
# refresh the numbers behind the summary doc — it does not write the doc itself.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from _shared.db_connection import query_df

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
MARTS = "develop.eros_analytics_marts"

# %% [markdown]
# ## 1. Table inventory: row counts, date range, null rates, duplicates

# %%
inventory = query_df(
    f"""
    select
      (select count(*) from {MARTS}.fct_sales) as fct_sales_rows,
      (select count(*) from {MARTS}.fct_daily_stock_levels) as fct_stock_rows,
      (select count(*) from {MARTS}.dim_products) as dim_products_rows,
      (select count(*) from {MARTS}.dim_locations) as dim_locations_rows,
      (select count(*) from {MARTS}.dim_calendary) as dim_calendary_rows,
      (select count(*) from {MARTS}.fct_returns) as fct_returns_rows
    """
)
inventory.to_csv(OUTPUT_DIR / "table_row_counts.csv", index=False)

fct_sales_quality = query_df(
    f"""
    select
      min(placed_at) as min_placed_at,
      max(placed_at) as max_placed_at,
      count(*) as total_rows,
      sum(case when placed_at is null then 1 else 0 end) as null_placed_at,
      sum(case when product_variant_id is null then 1 else 0 end) as null_product_variant_id,
      sum(case when location_id is null then 1 else 0 end) as null_location_id,
      sum(case when quantity is null then 1 else 0 end) as null_quantity,
      sum(case when unit_price is null then 1 else 0 end) as null_unit_price,
      sum(case when date_id = 19000101 then 1 else 0 end) as sentinel_date_id_rows
    from {MARTS}.fct_sales
    """
)
fct_sales_quality.to_csv(OUTPUT_DIR / "fct_sales_quality.csv", index=False)

fct_sales_dup_groups = query_df(
    f"""
    select count(*) as dup_groups from (
      select order_item_id, count(*) c
      from {MARTS}.fct_sales
      group by order_item_id
      having count(*) > 1
    )
    """
)

order_status_dist = query_df(
    f"select order_status, count(*) c from {MARTS}.fct_sales group by 1 order by 2 desc"
)
order_status_dist.to_csv(OUTPUT_DIR / "order_status_distribution.csv", index=False)

stock_quality = query_df(
    f"""
    select
      min(stock_level_day) as min_day,
      max(stock_level_day) as max_day,
      count(*) as total_rows,
      sum(case when physical_quantity_on_hand is null then 1 else 0 end) as null_qty,
      sum(case when is_negative_raw_quantity then 1 else 0 end) as negative_raw_rows,
      count(distinct product_variant_id) as distinct_products,
      count(distinct location_id) as distinct_locations
    from {MARTS}.fct_daily_stock_levels
    """
)
stock_quality.to_csv(OUTPUT_DIR / "fct_daily_stock_levels_quality.csv", index=False)

future_stock_rows = query_df(
    f"""
    select count(*) future_rows, min(stock_level_day) min_future, max(stock_level_day) max_future
    from {MARTS}.fct_daily_stock_levels
    where stock_level_day > current_date()
    """
)
future_stock_rows.to_csv(OUTPUT_DIR / "future_dated_stock_rows.csv", index=False)

dim_products_quality = query_df(
    f"""
    select count(*) total,
      sum(case when sale_price is null then 1 else 0 end) null_sale_price,
      sum(case when cost_price is null then 1 else 0 end) null_cost_price,
      sum(case when category_name is null then 1 else 0 end) null_category,
      sum(case when category_name = 'Não Classificado' then 1 else 0 end) unclassified
    from {MARTS}.dim_products
    """
)
dim_products_quality.to_csv(OUTPUT_DIR / "dim_products_quality.csv", index=False)

# %% [markdown]
# ## 2. `location_type` distinct values (store vs. warehouse split)

# %%
locations = query_df(
    f"""
    select location_id, location_name, location_type, is_active, updated_at
    from {MARTS}.dim_locations
    order by location_id
    """
)
locations.to_csv(OUTPUT_DIR / "dim_locations.csv", index=False)

sales_by_location_type = query_df(
    f"""
    select l.location_type, count(*) rows, sum(f.quantity) total_qty, count(distinct f.location_id) n_locations
    from {MARTS}.fct_sales f
    join {MARTS}.dim_locations l on f.location_id = l.location_id
    group by 1
    """
)
sales_by_location_type.to_csv(OUTPUT_DIR / "sales_by_location_type.csv", index=False)

channel_by_location_type = query_df(
    f"""
    select l.location_type, f.channel, count(*) rows, sum(f.quantity) qty
    from {MARTS}.fct_sales f
    join {MARTS}.dim_locations l on f.location_id = l.location_id
    group by 1, 2
    order by 1, 2
    """
)
channel_by_location_type.to_csv(OUTPUT_DIR / "channel_by_location_type.csv", index=False)

# %% [markdown]
# ## 3. 2020-2021 anomaly check — monthly + annual sales trend by year

# %%
monthly_sales = query_df(
    f"""
    select
      year(placed_at) as yr,
      month(placed_at) as mo,
      count(distinct order_id) as valid_orders,
      sum(quantity) as valid_qty,
      round(sum(line_total), 2) as gross_revenue
    from {MARTS}.fct_sales
    where order_status in ('paid', 'confirmed')
    group by 1, 2
    order by 1, 2
    """
)
monthly_sales.to_csv(OUTPUT_DIR / "monthly_sales_by_year.csv", index=False)

annual = (
    monthly_sales.groupby("yr")
    .agg(valid_orders=("valid_orders", "sum"), valid_qty=("valid_qty", "sum"), gross_revenue=("gross_revenue", "sum"))
    .reset_index()
)
annual["revenue_yoy_pct"] = annual["gross_revenue"].pct_change() * 100
annual.to_csv(OUTPUT_DIR / "annual_sales_totals.csv", index=False)

# like-for-like Jan-Aug comparison so the partial current year is comparable
jan_aug = (
    monthly_sales[monthly_sales["mo"] <= 8]
    .groupby("yr")
    .agg(valid_orders=("valid_orders", "sum"), valid_qty=("valid_qty", "sum"), gross_revenue=("gross_revenue", "sum"))
    .reset_index()
)
jan_aug["revenue_yoy_pct"] = jan_aug["gross_revenue"].pct_change() * 100
jan_aug.to_csv(OUTPUT_DIR / "jan_aug_comparable_totals.csv", index=False)

# %% [markdown]
# ## 4. Censored-demand check
#
# `fct_daily_stock_levels` is sparse (one row per stock CHANGE day) and, per
# `future_dated_stock_rows` above, the large majority of its rows are future-dated
# mock data. This check restricts to non-future rows, forward-fills per
# (product_variant_id, location_id), and compares against same/later-day sales.

# %%
stock = query_df(
    f"""
    select stock_level_day, product_variant_id, location_id, physical_quantity_on_hand
    from {MARTS}.fct_daily_stock_levels
    where stock_level_day <= current_date()
    """
)
stock["stock_level_day"] = pd.to_datetime(stock["stock_level_day"])
stock["product_variant_id"] = stock["product_variant_id"].astype(str)
stock["location_id"] = stock["location_id"].astype(str)

sales_daily = query_df(
    f"""
    select date(placed_at) as sale_day, product_variant_id, location_id, sum(quantity) as qty_sold
    from {MARTS}.fct_sales
    where order_status in ('paid', 'confirmed')
    group by 1, 2, 3
    """
)
sales_daily["sale_day"] = pd.to_datetime(sales_daily["sale_day"])
sales_daily["product_variant_id"] = sales_daily["product_variant_id"].astype(str)
sales_daily["location_id"] = sales_daily["location_id"].astype(str)

# NOTE: each (product,location) pair in the non-future window has, in practice,
# only a single stock snapshot (confirmed by exploration) — so "forward-fill" here
# is a single constant carried forward from that one snapshot date, not a real
# time series. Treat the resulting % as a rough signal, not a precise measurement
# (see caveats in the summary doc).
censored_check = sales_daily.merge(stock, on=["product_variant_id", "location_id"], how="inner")
censored_check = censored_check[censored_check["sale_day"] >= censored_check["stock_level_day"]]
censored_check["censored_flag"] = censored_check["qty_sold"] >= censored_check["physical_quantity_on_hand"]

censored_summary = pd.DataFrame(
    [
        {
            "comparable_observations": len(censored_check),
            "distinct_pairs_comparable": censored_check.groupby(["product_variant_id", "location_id"]).ngroups,
            "flagged_censored_observations": int(censored_check["censored_flag"].sum()),
            "flagged_pct": (
                round(100 * censored_check["censored_flag"].sum() / len(censored_check), 1) if len(censored_check) else None
            ),
        }
    ]
)
censored_summary.to_csv(OUTPUT_DIR / "censored_demand_check.csv", index=False)

# %% [markdown]
# ## 5. Print everything for a quick console review

# %%
if __name__ == "__main__":
    for name, df in [
        ("table_row_counts", inventory),
        ("fct_sales_quality", fct_sales_quality),
        ("fct_sales_dup_groups", fct_sales_dup_groups),
        ("order_status_dist", order_status_dist),
        ("stock_quality", stock_quality),
        ("future_stock_rows", future_stock_rows),
        ("dim_products_quality", dim_products_quality),
        ("locations", locations),
        ("sales_by_location_type", sales_by_location_type),
        ("channel_by_location_type", channel_by_location_type),
        ("annual_sales", annual),
        ("jan_aug_comparable", jan_aug),
        ("censored_demand_summary", censored_summary),
    ]:
        print(f"\n--- {name} ---")
        print(df.to_string())
