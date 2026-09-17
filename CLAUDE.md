# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Configuration

### to-tickets skill

- **Tracker:** Local files — write one Markdown file per ticket under `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, per the skill's local-ticket-template.
- **Triage label:** N/A for local files (the template's `Status: ready-for-agent` field covers this).

## What this project is

A data pipeline for the "Lighthouse" project (Grupo 10 / TeslaVinci): incremental ingestion from SQL Server into the Bronze layer of Databricks (Unity Catalog), followed by dbt transformations into a star schema, with LGPD governance (dynamic column masking, RBAC) and orchestration via Databricks Workflows.

**Note:** This is a mock database intended for learning purposes and does not update in production. The source data already contains some future-dated records which the team has decided to filter out via the `filter_valid_orders()` and related macros in `dbt/macros/data_quality_and_dedupe.sql`.

## Repository structure

This repo contains **three independent Databricks Asset Bundles** plus a dbt project. Each bundle has its own `databricks.yml` and is deployed/run separately — there is no single root bundle.

```
databricks/
  ingestion/       # Bundle "grupo10": SQL Server -> Bronze ingestion job
  transformation/  # Bundle "transformation": runs `dbt build` as a Databricks job task
  orchestration/   # Bundle "orchestration": top-level job that chains ingestion -> transformation
dbt/                # dbt project ("desafio_lh"): staging -> intermediate -> marts (star schema)
forecasting/        # Exploratory demand-forecasting workstream, not a committed dbt/Databricks bundle (see below)
```

`databricks/orchestration` does **not** reference the other two bundles by include; it wires them together at the Databricks job level via hardcoded `job_id`s in `orchestration_job.yml` (`run_job_task`), so the ingestion and transformation jobs must already be deployed before the orchestration job can run.

Each bundle target (`dev`/`prod`) is configured in its own `databricks.yml`. `dev` is always the default target and resolves to per-user schemas (e.g. `${workspace.current_user.short_name}_analytics`); `prod` points at the `lh_nautical` catalog on a fixed workspace host. Local, uncommitted overrides (per-developer workspace host / schema) live in `databricks.local.yml` at the repo root, included by the ingestion and orchestration bundles — each developer creates their own copy; it is not checked in.

Note: the top-level `src/` and `tests/` directories at the repo root are stale leftovers (only `__pycache__` remains, referencing modules that no longer exist as source). The live ingestion Python package is `databricks/ingestion/src/grupo10/`.

## Commands

Install dependencies (uv-managed project, Python >=3.10,<3.13):
```bash
uv sync --dev
```

Run ingestion tests (uses Databricks Connect against a real/serverless workspace — requires `databricks auth login` first, not a local mock):
```bash
cd databricks/ingestion && uv run pytest
```

Lint (ruff, configured at the repo root, line-length 120):
```bash
uv run ruff check .
```

Deploy / run a specific bundle (run from within that bundle's directory, e.g. `databricks/ingestion`):
```bash
databricks bundle deploy --target dev   # or prod
databricks bundle run ingestion         # job name as defined in that bundle's resources/*.yml
```

dbt (run from `dbt/`, against a configured `desafio_lh` profile — in CI/CD this runs as the `dbt_build` task inside the `transformation` bundle instead):
```bash
dbt deps
dbt build
dbt docs generate && dbt docs serve
```

There is no configured CI (bitbucket-pipelines.yml is still the unfilled starter template) — treat `pytest`, `ruff`, and `dbt build` above as the checks to run manually before considering a change done.

## Ingestion architecture (`databricks/ingestion`)

The `ingestion` job (`resources/ingestion.job.yml`) runs as notebook tasks against Bronze:

```
setup -> ingest_tables (for_each per table, concurrency 5) -> ingest_bcb_exchange_rates -> check_bcb_consecutive_failures (only on failure)
```

- `setup` creates the catalog/schema, control/audit tables, and emits the list of tables (from `tables_config.json`) for the `for_each_task` to fan out over.
- Per-table ingestion strategy is chosen by primary key shape in `run_incremental_ingestion()` (`src/grupo10/ingest.py`):
  - **Single key** (e.g. `"id"`) → incremental watermark pagination (`_ingestion_control` table tracks `last_processed_id`), appended in batches of `DEFAULT_LINES_PER_BATCH`.
  - **Composite key** (e.g. `stock_levels`, `product_suppliers`, `variant_attribute_values`) → full reload + MERGE via `_merge_into_delta()`, keyed on all PK columns.
  - All writes are idempotent; a batch write failure re-raises so the Databricks task fails and can be selectively rerun.
- `_ingestion_audit` records status/duration/row-count/error per table run (`src/grupo10/utils/audit.py`).
- `src/grupo10/utils/alerting.py` tracks a separate daily run-history table keyed by `(task_name, run_date)` and computes consecutive-failure streaks — used by `check_bcb_consecutive_failures.ipynb` to trigger the native on_failure email only after repeated failures, not a single blip.
- Sensitive columns are masked dynamically via a Unity Catalog UDF (`governance_setup.ipynb`) driven by `governance_config.json`; RBAC grants are applied in `apply_rbca.ipynb`. Credentials come from `dbutils.secrets.get()` in the `sqlserver` scope, never hardcoded.

## dbt architecture (`dbt/`)

Project name `desafio_lh`, profile `desafio_lh`. Three layers under `models/`, each with its own schema suffix set in `dbt_project.yml`:

- **staging** (views, `+schema: staging`) — 1:1 cleanup/typing of Bronze sources (`stg_*.sql`), sources declared in `models/staging/src_bronze.yml`.
- **intermediate** (views, `+schema: intermediate`) — cross-entity business logic (`int_products_categorized`, `int_sales_enriched`, `int_purchases_enriched`, `int_returns_enriched`, `int_supplier_delivery_delay`).
- **marts** (tables, `+schema: marts`) — star schema: dimensions (`dim_calendary`, `dim_customers`, `dim_customer_addresses`, `dim_employees`, `dim_locations`, `dim_products`, `dim_suppliers`) and facts (`fct_sales`, `fct_daily_stock_levels`, `fct_purchases`, `fct_returns`), plus a pre-aggregated `marts/aggregates/` subfolder built for BI consumption directly (see below).

Schema resolution is environment-aware via the custom `generate_schema_name` macro (`macros/generate_schema_name.sql`): in `dev`, layer schemas are suffixed onto each developer's own schema (`<user>_analytics_staging`, etc.) for isolation; in `prod`, the layer name is used directly (`staging`, `intermediate`, `marts`).

### Marts reference for BI / DAX work (grain and keys)

Dimensions:
- `dim_customers` — 1 row per customer (`customer_sk`); carries `person_type` (PF individual / PJ corporate).
- `dim_customer_addresses` — **SCD2**, 1 row per address version (`customer_address_sk`), `is_current` / `valid_from` / `valid_to` flag the active version; FK `customer_id`.
- `dim_products`, `dim_locations`, `dim_employees`, `dim_suppliers`, `dim_calendary` (`date_id`, integer `YYYYMMDD`).

Transaction-grain facts:
- `fct_sales` — 1 row per order item (`sales_sk`). Product FK is `product_variant_sk` (renamed from `product_sk` — check for stale references to the old name). `order_status` includes `paid`/`confirmed`/`cancelled`/`draft`, but only `paid`+`confirmed` count as valid revenue — filter or use the pre-filtered aggregates below instead of summing `fct_sales` raw. `date_id` falls back to `19000101` (no match in `dim_calendary`) when `placed_at` is null — such rows land in Power BI's blank relationship row; expect and don't "fix" that in a DAX measure.
- `fct_returns` — 1 row per returned item (`return_sk`), bridges to `fct_sales` via `order_item_id`. `product_variant_sk`/`returned_variant_id` now correctly point to the **originally sold/returned** product (not the exchange); `exchange_variant_id` is the separate replacement product when `action = 'exchange'`. Unlike `fct_sales`, `date_id` here has invalid/null/future dates filtered out at the model level rather than falling back to `19000101`.
- `fct_purchases`, `fct_daily_stock_levels` — supplier purchases and daily inventory snapshots, not directly relevant to sales/customer KPIs.

Pre-aggregated marts (`marts/aggregates/`) — prefer these as the DAX/Power BI source over hand-rolling the same logic from the transaction facts:
- `agg_customer_metrics` — **1 row per customer.** Gross/net LTV, first/last purchase date, `is_churn_risk` (segmented threshold: 180d PJ / 240d PF), dynamic ABC class (`A`/`B`/`C` by revenue concentration), `inferred_purchase_reason`.
- `agg_customer_monthly` — **1 row per (`customer_id`, `reporting_month`).** Date-spined and zero-filled from each customer's first purchase month forward (rows exist even for no-purchase months) — built for cohort/MRR/MoM-retention DAX rather than plain SUM aggregation.
- `agg_product_performance` — **1 row per (`performance_month`, `product_variant_id`).** Gross/net quantity and revenue, returns, taxes, COGS (net qty × standard cost), `contribution_margin` (net revenue − COGS).
- `agg_sales_daily` — **1 row per (`date_id`, `channel`).** Gross/net revenue, returns, taxes, valid/canceled order volume, valid item volume (basket-size base).
- `agg_sales_regional_category_daily` — **1 row per (`date_id`, `channel`, `customer_state`, `category_name`).** Items/revenue only — deliberately excludes order counts to avoid fan-out double-counting on multi-category orders.
- `agg_sales_regional_orders_daily` — **1 row per (`date_id`, `channel`, `customer_state`).** Order counts only, split out from the category aggregate for the same fan-out reason — join/blend the two by their shared grain in DAX rather than expecting one table to carry both order counts and category breakdowns.

All aggregates already net out cancellations, returns, and ICMS/IPI taxes per their column descriptions — check each `.yml` before re-deriving a "net" figure in DAX to avoid double-counting.

`fct_daily_stock_levels` is an incremental model with **deferred surrogate-key backfill**: because `dim_products`/`dim_locations` rows can arrive after the corresponding fact rows, `product_sk`/`location_sk` are populated best-effort on insert and then repaired by a `post_hook` MERGE that fills any still-`NULL` surrogate keys once the dimension row shows up (see current branch `fix/surrogate-keys`). When touching this model, keep both the `merge` incremental strategy and that post-hook in sync — a naive `insert_overwrite`-style rewrite would defeat the late-arrival repair.

Shared macros: `dedupe_latest()`, `keep_required_rows()`, and `filter_valid_orders()` (`macros/data_quality_and_dedupe.sql`) handle `qualify row_number()` deduping, dropping rows with missing mandatory columns, and filtering out invalid/future-dated orders — used across staging/intermediate models rather than repeating the pattern inline. `convert_currency()` and `days_between()` (own files under `macros/`) handle USD/BRL conversion (via `stg_exchange_rates`) and date-diff arithmetic, both used in `int_purchases_enriched`/`int_supplier_delivery_delay`.

`snapshots/snap_stock_levels.sql` (timestamp strategy on `stg_stock_levels`, keyed on `stock_level_id`) is the SCD2 history feeding `fct_daily_stock_levels`. `seeds/seed_category_fix.csv` is a manual lookup (by `product_type`) that `int_products_categorized` joins against to correct miscategorized/misspelled product types from the source system.

Tests live in `dbt/tests/` as one directory per fact table (`fct_daily_stock_levels/`, `fct_purchases/`, `fct_returns/`) containing singular assertion SQL (e.g. no negative quantities, no future dates, 7-day reconciliation against source snapshots) in addition to schema tests declared in each model's `.yml`.

## Demand forecasting workstream (`forecasting/`)

Exploratory only, not a committed dbt model or Databricks bundle. Connects to the dev marts via `forecasting/_shared/db_connection.py`, which reads credentials from the existing `~/.dbt/profiles.yml` dev profile (no secrets stored in-repo). Ten numbered stages so far (`01`-`10`), each with a script/SQL that produces it and a markdown writeup, plus an `experiments/` directory for Stage 3 model comparisons (see below) — see [`forecasting/README.md`](forecasting/README.md) for the full run order and [`forecasting/OVERVIEW.md`](forecasting/OVERVIEW.md) for the complete stage-by-stage narrative; this section only calls out the highlights most relevant to picking up new work:

- `01_data_exploration/` — inventories the transformation layer for forecasting readiness. Key conclusion: **no existing mart is at product x store x day grain** — `agg_product_performance` is product x month with no location; the regional aggregates group by customer state, not selling location.
- `02_schema_design/` — proposes and prototypes `fact_demand_daily` (date x `product_variant_id` x `location_id`, dense/zero-filled), built in a disposable scratch schema (`<dev_schema>_forecasting_scratch`, e.g. `user_analytics_forecasting_scratch`), reconciled exactly against `fct_sales`. Weekly/monthly grains roll up from this table via SQL, never reprocessing `fct_sales`.
- `03_granularity_baselines/` — full-catalog backtest of Seasonal Naive / Moving Average / SES at daily, weekly, and monthly grain (baselines only, no ML model). **Weekly is the recommended default grain**: daily is dominated by per-SKU sparsity (73% of observations are legitimately zero), monthly loses the peak-season signal Moving Average/SES need to react to. Seasonal Naive wins accuracy per-series at every grain but carries a structural growth-trend bias (the business grows ~15%/year, so "same period last year" systematically underforecasts) — the trend component this note anticipated is exactly what `10_feature_engineering` had to add retroactively as a structural control (see below).
- `04`-`09` — demand-pattern classification, Croston/SBA and ADIDA backtests, hierarchical (Bottom-Up/Top-Down/MinT) reconciliation, decision-horizon/product-axis evaluation, and the Phase 1 close-out (genuine 91-day held-static baseline logged to `/Shared/00_baseline` in MLflow). See `OVERVIEW.md` for details — not re-summarized here to avoid drifting out of sync with it again.
- `10_feature_engineering/` — Stage 2 (tasks 2.1-2.10): a pooled fixed-effects panel regression (product x location x ISO-week, entity effects + a linear trend control) testing calendar, holiday, weather, economic, marketing, and internal/inventory features one cumulative layer at a time against a >2% MAPE-improvement threshold. **Only calendar survives into the production feature set** (via an accuracy ablation, not its own threshold — nothing individually cleared 2%); everything else is not kept, not testable with current data, or a structural control. [`10_feature_engineering/10_frozen_feature_set.md`](forecasting/10_feature_engineering/10_frozen_feature_set.md) is the fixed input for every Stage 3 (task 3.n) session — no further changes to it without a new, explicit team decision. Logged to `/Shared/01_feature_iteration` in MLflow.
- `experiments/` — Stage 3 (tasks 3.n) model comparisons. One folder per person per model (`experiments/<name>_<model>/`, e.g. `eva_xgboost/`) so work doesn't collide; results land in one shared MLflow experiment for cross-model comparison. **Every model must import and score through `experiments/_shared/evaluate.py`** — the mandatory shared protocol, regardless of what grain the model is fit at internally (daily, weekly, whatever suits the method): sum predictions into a total per (`product_variant_id`, `location_id`) over the same four non-overlapping 91-day rolling-origin windows `09_baseline_close_out` established (2024-12-31 / 2025-04-01 / 2025-07-01 / 2025-09-30), training only on data up to each cutoff, refit per window, and compare against the `seasonal_naive_genuine_91d_v2` champion in `/Shared/00_baseline` via `compare_to_baseline()` (which also warns if a model's `actual_total` per window drifts >0.5% from the baseline's — a sign the window definition or source filter diverged). Reports at two levels — SKU x location (`evaluate()`) and category x location (`to_category_level()`, joins `dim_products`, sums the *same* window totals rather than re-forecasting) — with RMSE/bias per series and portfolio WAPE per window, always reported per window rather than one averaged number; MAPE/sMAPE stay excluded, per `05_croston_sba`'s finding that they're structurally uninformative on this catalog. **This module exists because `10_feature_engineering`'s panel regression used a different, incompatible evaluation setup** (weekly grain, continuously refit across a full holdout year, benchmarked only against its own no-features reference — see `10_feature_engineering/_shared/panel_regression.py`'s docstring) — scoring a Stage 3 candidate that way instead would repeat the exact leakage trap `09_baseline_close_out` already caught once (recomputing a forecast as time passes lets it see real future actuals early, which is why `08_decision_horizon_and_product_axis`'s 22-35% WAPE collapsed to 122-226% once genuinely held static). See [`experiments/README.md`](forecasting/experiments/README.md) for the full usage example.

## Code style

- Add brief comment descriptions for each function or block of logic to explain **what** it does. Comments should be concise (one line, typically) and placed directly above or inline with the code they describe. Example:
  ```sql
  -- Normalize postal codes to Brazilian standard XXXXX-XXX format, strip non-numeric chars
  case
      when postal_code is not null
      then concat(
          substr(trim(regexp_replace(postal_code, '[^0-9]', '')), 1, 5),
          '-',
          substr(trim(regexp_replace(postal_code, '[^0-9]', '')), 6, 3)
      )
      else null
  end as postal_code,
  ```

## Testing and validation

- After making any changes to a dbt model, run `dbt build -s <model_name>` to verify the changes don't break anything. This builds only the changed model and its upstream/downstream dependencies, catching syntax errors, broken references, and test failures without the overhead of a full rebuild.
  ```bash
  dbt build -s dim_customer_addresses
  ```
