# dbt project: `desafio_lh`

Transforms the Bronze layer (`<catalog>.bronze`) into a star schema on Databricks. The generated documentation, with column descriptions, tests and the lineage graph, is published at **https://leopinho1777.github.io/databricks-lighthouse-project/**.

A full build processes 44 models, 414 tests, 1 snapshot and 1 seed.

## Layers

| Layer | Materialization | Schema (prod) | Purpose |
| :--- | :--- | :--- | :--- |
| `staging` | view | `staging` | Technical cleanup of Bronze: naming, typing, deduplication with `dedupe_latest()`, dropping rows without mandatory columns |
| `intermediate` | view | `intermediate` | Cross-entity business rules and enrichment |
| `marts` | table | `marts` | Star schema (dimensions and facts) plus `marts/aggregates/` built for BI |

Seeds are placed in `staging`, and the stock-level snapshot in `snapshots`.

### Schema naming per environment

The `generate_schema_name` macro ([`macros/generate_schema_name.sql`](macros/generate_schema_name.sql)) isolates developers:

* **dev:** each layer is appended to the developer's schema, for example `<user>_analytics_staging`.
* **prod:** the layer name is used directly: `staging`, `intermediate`, `marts`.

## Models

**Staging** (22): `stg_addresses`, `stg_brands`, `stg_categories`, `stg_customers`, `stg_employees`, `stg_exchange_rates`, `stg_fiscal_invoices`, `stg_goods_receipt_items`, `stg_goods_receipts`, `stg_locations`, `stg_order_items`, `stg_orders`, `stg_payments`, `stg_product_variants`, `stg_products`, `stg_purchase_order_items`, `stg_purchase_orders`, `stg_return_items`, `stg_returns`, `stg_stock_levels`, `stg_stock_movements`, `stg_suppliers`.

**Intermediate** (5):

* `int_products_categorized`: products, variants, brands and the category hierarchy; product types are corrected through the `seed_category_fix` seed.
* `int_sales_enriched`: orders, items, payments and invoices combined.
* `int_returns_enriched`: returned items with their return header context.
* `int_purchases_enriched`: purchase orders with item and receipt data, converted to BRL.
* `int_supplier_delivery_delay`: delivery delay metrics per purchase order.

**Marts** (17):

* Dimensions (7): `dim_calendary`, `dim_customers`, `dim_customer_addresses` (SCD Type 2), `dim_employees`, `dim_locations`, `dim_products`, `dim_suppliers`.
* Facts (4): `fct_sales` (one row per order item), `fct_returns`, `fct_purchases`, `fct_daily_stock_levels` (incremental, with a post-hook that backfills surrogate keys for late-arriving dimension rows).
* Aggregates (6, in `marts/aggregates/`): `agg_customer_metrics`, `agg_customer_monthly`, `agg_product_performance`, `agg_sales_daily`, `agg_sales_regional_category_daily`, `agg_sales_regional_orders_daily`. They already net out cancellations, returns and taxes, so prefer them over summing the facts for BI.

## Macros

Shared logic lives in [`macros/`](macros): `dedupe_latest()`, `keep_required_rows()` and `filter_valid_orders()` for data quality, `filter_future_dated()` with the `no_future_dates` test for the future-dated records in the source, `convert_currency()` for USD/BRL conversion, `days_between()` and `generate_schema_name()`.

## Tests

Schema tests are declared in each model's `.yml` (not null, unique, relationships, accepted values, `dbt_utils` checks). Singular tests in [`tests/`](tests) cover the facts, for example no negative quantities, no future dates, and a 7-day reconciliation of stock movements.

## Commands

Run from this directory with the `desafio_lh` profile configured in `~/.dbt/profiles.yml`. The source tables are read from `<target catalog>.bronze`.

```bash
dbt deps                       # install dbt_utils and codegen
dbt build --target prod        # seeds, snapshot, models and tests
dbt build -s <model_name>      # build one model with its upstream and downstream dependencies
dbt docs generate              # build the documentation site
```

In the deployed pipeline this project runs as the `dbt_build` task of the `transformation` bundle (`databricks/transformation`).
