# %% [markdown]
# # Build the `fact_demand_daily` prototype
#
# Executes `fact_demand_daily_prototype.sql` against the live dev warehouse and
# runs a few sanity checks against known `fct_sales` totals.

# %%
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared.db_connection import query_df, run_query

SQL_PATH = Path(__file__).parent / "fact_demand_daily_prototype.sql"
TABLE = "develop.eros_analytics_forecasting_scratch.fact_demand_daily"

# %%
if __name__ == "__main__":
    sql = SQL_PATH.read_text(encoding="utf-8")
    print("Building fact_demand_daily prototype...")
    run_query(sql)

    row_count = query_df(f"select count(*) as n from {TABLE}")
    print(f"\nRow count: {row_count.iloc[0]['n']:,}")

    # Sanity check: pick one real (product, location) day and confirm the
    # prototype's qty_sold_gross matches a manual fct_sales sum.
    sample = query_df(
        f"""
        select product_variant_id, location_id, date_id
        from {TABLE}
        where qty_sold_gross > 0
        limit 1
        """
    )
    pid, lid, did = sample.iloc[0][["product_variant_id", "location_id", "date_id"]]

    prototype_val = query_df(
        f"""
        select qty_sold_gross from {TABLE}
        where product_variant_id = '{pid}' and location_id = '{lid}' and date_id = {did}
        """
    ).iloc[0]["qty_sold_gross"]

    manual_val = query_df(
        f"""
        select sum(quantity) as qty from develop.eros_analytics_marts.fct_sales
        where product_variant_id = '{pid}' and location_id = '{lid}' and date_id = {did}
          and order_status in ('paid', 'confirmed')
        """
    ).iloc[0]["qty"]

    print(f"\nSpot check — product {pid}, location {lid}, date {did}:")
    print(f"  prototype qty_sold_gross = {prototype_val}")
    print(f"  manual fct_sales sum     = {manual_val}")
    assert prototype_val == manual_val, "MISMATCH — prototype does not match fct_sales"
    print("  MATCH")

    # Whole-table reconciliation: total qty_sold_gross should equal fct_sales'
    # total valid-order quantity.
    total_prototype = query_df(f"select sum(qty_sold_gross) as n from {TABLE}").iloc[0]["n"]
    total_fct_sales = query_df(
        """
        select sum(quantity) as n from develop.eros_analytics_marts.fct_sales
        where order_status in ('paid', 'confirmed')
        """
    ).iloc[0]["n"]
    print(f"\nTotal qty_sold_gross (prototype): {total_prototype:,}")
    print(f"Total valid quantity (fct_sales):  {total_fct_sales:,}")
    assert total_prototype == total_fct_sales, "MISMATCH — totals do not reconcile"
    print("MATCH — prototype reconciles with fct_sales")
