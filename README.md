# README

Delivery repository for the Lighthouse project — Group 10 / TeslaVinci.

Incremental ingestion pipeline from SQL Server into the Bronze layer on Databricks (Unity Catalog), followed by dbt transformations into a star schema, with LGPD governance (dynamic masking and RBAC) and orchestration through Databricks Workflows.

---

## Project Structure

```
databricks/
  ingestion/                            # Bundle "grupo10": SQL Server and BCB -> Bronze
    databricks.yml                      # Bundle definition (dev/prod targets)
    resources/
      ingestion.job.yml                 # Ingestion job (4 tasks)
    src/
      tables_config.json                # 24 tables and their primary keys
      governance_config.json            # Sensitive columns per table (LGPD)
      sqlserver_ingest_setup.ipynb      # Setup task: catalog/schema, audit/control tables, table list
      sqlserver_ingest.ipynb            # Ingests one table (one for_each iteration)
      bcb_exchange_rates_ingest.ipynb   # BCB USD/BRL exchange rate ingestion
      check_bcb_consecutive_failures.ipynb  # Alerts after consecutive BCB failures
      governance_setup.ipynb            # Creates the dynamic masking UDF
      apply_rbca.ipynb                  # Applies RBAC grants
      grupo10/
        ingest.py                       # Extract/load logic (incremental + MERGE)
        utils/audit.py                  # Audit table and records
        utils/alerting.py               # Run history and consecutive-failure streaks
        utils/logger.py                 # Pipeline logging
    tests/                              # pytest configuration (Databricks Connect)
  transformation/                       # Bundle "transformation": runs dbt as a Databricks job
  orchestration/                        # Bundle "orchestration": chains ingestion -> transformation
dbt/                                    # dbt project (desafio_lh): staging -> intermediate -> marts
docs/
  dashboard_guide.md                    # Power BI executive dashboard guide
pyproject.toml                          # Python dependencies (uv)
databricks.local.yml                    # Local overrides (not versioned, see Prerequisites)
```

---

## Architecture

* **Three Databricks Asset Bundles** under `databricks/`, each with its own `databricks.yml` and deployed separately: `ingestion` (bundle `grupo10`), `transformation` and `orchestration`.
* **`pyproject.toml`** (repository root): Python dependencies, managed with uv.
* **`resources/`** (in each bundle): Databricks job definitions.
* **Destination**: `lh_nautical` catalog, `bronze` schema (Unity Catalog), Delta Lake format. In the `dev` target, ingestion writes to the `develop` catalog.

### Ingestion job

`databricks/ingestion/resources/ingestion.job.yml` defines 4 tasks:

```
setup ──┬──> ingest_tables              (for_each: one run per table, concurrency 5)
        └──> ingest_bcb_exchange_rates  ──(only if it fails)──> check_bcb_consecutive_failures
```

* `setup` creates the catalog, schema, audit and control tables, and publishes the list of tables to ingest.
* `ingest_tables` and `ingest_bcb_exchange_rates` run in parallel after `setup`.
* `check_bcb_consecutive_failures` runs only when the BCB task fails, and fails on purpose on the 3rd consecutive failed day to trigger its on_failure email.

`governance_setup.ipynb` and `apply_rbca.ipynb` are standalone notebooks: they are not part of the ingestion job.

### Orchestration

`databricks/orchestration/resources/orchestration_job.yml` defines the "LH Nautical Orchestration" job: it runs the ingestion job and then the transformation job (`dbt deps` + `dbt build`), each with up to 2 retries. Both jobs are referenced by `job_id`, so they must be deployed before the orchestration job can run.

---

## Ingestion Strategy

The logic is modularized in `databricks/ingestion/src/grupo10/ingest.py`. For each table, `run_incremental_ingestion()` picks the strategy based on the primary key:

* **Single key** (e.g. `"id"`): incremental by watermark, appended with `mode("append")`.
* **Composite key** (e.g. `["product_variant_id", "location_id"]`): full reload through `_merge_into_delta()`.

**24 tables** are mapped in `tables_config.json`, 3 of which use a composite key (`stock_levels`, `product_suppliers`, `variant_attribute_values`).

All writes are idempotent (MERGE or watermark), which prevents duplicates on reruns. Internal tables support ingestion control, auditing and alerting:

| Table | Role |
| :--- | :--- |
| **`_ingestion_control`** | Watermark per table; read at the start and updated at the end of each run. |
| **`_ingestion_audit`** | Run history: status, duration, row count and error. |
| **`_alert_run_history`** | Daily outcome of the BCB task, used to count consecutive failures. |

On failure, the exception is re-raised so the Workflow marks the task as failed, allowing a selective rerun of the affected table.

---

## Governance and Security (LGPD)

Dynamic masking through Unity Catalog: the `regra_mascaramento` function returns the original value for `admins` and `engenharia_dados`, and `████████ (RESTRITO LGPD)` for everyone else. Sensitive columns are mapped in `governance_config.json`.

Credentials are read with `dbutils.secrets.get()` (`sqlserver` scope in Databricks).

---

## Data Transformation Layer (dbt)

The data transformation stage is orchestrated with dbt (data build tool) on Databricks, following modular analytics engineering principles and a clear separation of responsibilities between layers.

## Schema Architecture and Environment Isolation

To keep tests reliable and prevent one developer's work from overwriting another's, schemas are resolved dynamically by a custom macro (`generate_schema_name`):

* **Development (dev):** every layer of each developer is isolated in individual schemas prefixed with the developer's credential (`<user>_analytics_<layer>`), for example: `user_analytics_staging`, `user_analytics_intermediate` and `user_analytics_marts`.
* **Suffix and standardization:** each layer automatically applies its matching suffix in Databricks.

## Model Structure

The project has compiled and validated models and tests, split across three main layers:

```
models/
├── staging/          # Cleaning, standardization and typing of raw data
├── intermediate/     # Business rules, enrichment and complex relationships
└── marts/            # Dimensional modeling ready for analysis (star schema)
```

### 1. Staging Layer

Responsible for technical cleaning, naming standardization, duplicate removal and correct typing of the data coming from the Bronze layer.

* **Customers and locations:** stg_addresses, stg_customers, stg_employees, stg_locations
* **Catalog and products:** stg_brands, stg_categories, stg_products, stg_product_variants
* **Sales, finance and operations:** stg_orders, stg_order_items, stg_payments, stg_fiscal_invoices, stg_returns, stg_return_items, stg_exchange_rates
* **Supply and inventory:** stg_suppliers, stg_purchase_orders, stg_purchase_order_items, stg_goods_receipts, stg_goods_receipt_items, stg_stock_levels, stg_stock_movements

### 2. Intermediate Layer

Responsible for centralizing intermediate business rules, cross-entity joins and operational metrics.

* **int_products_categorized:** consolidates products, variants, brands and the category hierarchy.
* **int_sales_enriched:** enriches sales transactions by combining orders, items, payments and invoices.
* **int_returns_enriched:** enriches returned items with their return header context (customer, location, status, reason).
* **int_supplier_delivery_delay:** calculates delivery delay metrics for supplier purchase orders.
* **int_purchases_enriched:** consolidates and enriches purchase orders by integrating item and receipt data.

### 3. Marts Layer

Contains the final dimensional models (fact and dimension tables) in a star schema, optimized for analytical queries and BI tools.

#### Dimension Tables

* **dim_calendary:** date dimension for trend and seasonality analysis.
* **dim_customers:** consolidated view of customers and their addresses.
* **dim_customer_addresses:** customer address history (SCD Type 2).
* **dim_employees:** employee records and profiles.
* **dim_locations:** physical locations and branches.
* **dim_products:** full product catalog dimension, with attributes and categories.
* **dim_suppliers:** supplier records and attributes.

#### Fact Tables

* **fct_sales:** sales fact at order-item grain, with amounts and financial metrics.
* **fct_daily_stock_levels:** daily stock levels per product and location, built from stock level snapshots.
* **fct_purchases:** purchases and supply fact, consolidating purchase order and supplier receipt metrics.
* **fct_returns:** returns fact, consolidating metrics on returned items, reasons and the financial/operational impact of returns.

#### Aggregate Tables

Pre-aggregated tables in `marts/aggregates/`, built for direct BI consumption: agg_sales_daily, agg_sales_regional_category_daily, agg_sales_regional_orders_daily, agg_product_performance, agg_customer_metrics, agg_customer_monthly.

## How to Generate the dbt Documentation

Running `dbt docs generate` makes dbt generate the full documentation of the transformation process.
Then `dbt docs serve` opens a local HTML site with an interactive interface containing all the project information.

---

## Scheduling

The orchestration job (`databricks/orchestration/resources/orchestration_job.yml`) runs daily at **01:00 (America/Sao_Paulo)** through the Quartz cron `0 0 1 * * ?`, with status `UNPAUSED`. It runs the ingestion job first and then the transformation job. The ingestion job has no schedule of its own.

---

## Prerequisites

* **Databricks CLI** installed and configured.
* **uv** (Python package manager).
* Access to a Databricks workspace with permission to create catalogs, schemas and jobs.

Bundle targets: `dev` (default) and `prod`. In `dev`, the transformation bundle writes to a per-user schema. Local/sensitive settings live in `databricks.local.yml` at the repository root, which must be created manually after cloning (it is not versioned); the ingestion and orchestration bundles include it.

---

## How to Run

```bash
# 1. Install dependencies (repository root)
uv sync --dev

# 2. Authenticate
databricks auth login

# 3. Store the SQL Server secrets in a Databricks secret scope
databricks secrets create-scope sqlserver
databricks secrets put-secret sqlserver username <value>
databricks secrets put-secret sqlserver password <value>
databricks secrets put-secret sqlserver host <value>
databricks secrets put-secret sqlserver port <value>
databricks secrets put-secret sqlserver db <value>

# 4. Deploy each bundle from its own folder (ingestion and transformation before orchestration)
(cd databricks/ingestion && databricks bundle deploy --target dev)       # or --target prod
(cd databricks/transformation && databricks bundle deploy --target dev)
(cd databricks/orchestration && databricks bundle deploy --target dev)

# 5. Run the ingestion manually
(cd databricks/ingestion && databricks bundle run ingestion)
```
