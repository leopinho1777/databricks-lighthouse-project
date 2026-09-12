# Ideal Schema Proposal — `fact_demand_daily`

> **Updated after develop merge on 2026-09-11.** Rebuilt against the corrected `fct_daily_stock_levels` (future-date filter fix + mart full-refresh). Row count and reconciliation re-confirmed below with fresh numbers. Open question #7 (stock data reliability) is updated — the future-dating half is resolved, the sparse-history half is not (see `01_data_exploration_summary.md` §4 for full detail).

A model-ready fact table at (date x product x store) grain, since nothing in the existing transformation layer is at that grain (`agg_product_performance` is product x month only; `agg_sales_regional_*` group by customer state, not selling location — see `01_data_exploration_summary.md` §1 and the CLAUDE.md marts reference). This is an **exploratory prototype**, not a committed dbt model: it lives in `develop.eros_analytics_forecasting_scratch.fact_demand_daily`, a dedicated scratch schema, built by [`fact_demand_daily_prototype.sql`](fact_demand_daily_prototype.sql) via [`build_prototype.py`](build_prototype.py). It's disposable and rebuildable at will; promoting it into `dbt/models/marts/` is a decision for a later phase once the team has reviewed this design.

**Built and verified against live dev data:** 14,802,030 rows (row count grew from the original 14,662,788 due to ~6 days of additional mock data accrued between builds — not related to the fix). Reconciles exactly against `fct_sales` (spot-checked one series manually, and confirmed the whole-table `sum(qty_sold_gross)` equals `fct_sales`' total valid-order quantity, both bounded to exclude the current/incomplete day: 649,523 = 649,523 — see `build_prototype.py` output). Pair count (distinct `product_variant_id` x `location_id` combinations) is unchanged at 6,054, confirming the spine wasn't affected by the stock-data fix even though `fct_daily_stock_levels` itself shrank considerably (see below) — every pair was already reachable via `fct_sales` alone.

## Grain and columns

Grain: one row per (`date_id`, `product_variant_id`, `location_id`) — dense, zero-filled where no sale occurred.

| column | type | source | notes |
|---|---|---|---|
| `date_id` | int (YYYYMMDD) | `dim_calendary` | FK to dim_calendary |
| `date_day` | date | `dim_calendary` | kept alongside `date_id` for date-arithmetic joins (e.g. Seasonal Naive's year-prior lookup) |
| `product_variant_id` | string | `fct_sales` / `fct_daily_stock_levels` | FK to dim_products |
| `location_id` | string | `fct_sales` / `fct_daily_stock_levels` | FK to dim_locations |
| `location_type` | string | `dim_locations` | denormalized for cheap store-vs-warehouse filtering without a join. Verified clean: exactly `'store'` or `'warehouse'`, 3 of each, no other values (§ below) |
| `qty_sold_gross` | decimal | `fct_sales`, `order_status in ('paid','confirmed')` | zero-filled |
| `qty_returned` | decimal | `fct_returns`, bridged to the *original* sale's date/location via `order_item_id` | zero-filled; matches the existing `agg_sales_daily` convention of netting returns against the original sale date rather than the return date |
| `qty_sold_net` | decimal | `qty_sold_gross - qty_returned` | this is the forecasting target used in Deliverable 3 |
| `revenue_net` | decimal | `fct_sales.line_total - fct_returns.refund_amount` | zero-filled |
| `stock_on_hand` | decimal | `fct_daily_stock_levels.physical_quantity_on_hand`, forward-filled | **unreliable — see caveat below** |
| `is_stockout_day` | boolean | `stock_on_hand = 0` | same caveat |
| `is_demand_censored_flag` | boolean | `qty_sold_gross >= stock_on_hand` | heuristic, same caveat |
| `source_built_at` | timestamp | build time | auditability |

## Spine construction

- **Product x location pairs:** the union of distinct pairs from `fct_sales` and `fct_daily_stock_levels` (not the raw `dim_products x dim_locations` cross join, in case a product/location exists in the dimension but has never transacted or held stock). In the current dev data this union equals the full cross join anyway — every one of the 1,009 products has sold at all 6 locations — but the "ever transacted" filter is kept so the logic stays correct as the catalog grows.
- **Date range:** a single **global** bound (`min(fct_sales.placed_at)` to yesterday), not a per-pair bound. This was the simpler of the two options considered in planning (global vs. per-pair `[first_transaction_date, last_complete_date]`) and is what's implemented. **Trade-off to flag for the team:** because every series is zero-filled uniformly from the global 2020-01-01 start, a product that was actually introduced later (e.g. mid-2023) is indistinguishable in this table from a product that existed the whole time and legitimately had zero demand — both just show as rows of `0`. If "when was this product actually launched" matters for Phase 2/3 (it does for any lookback-window feature), the schema should be rebuilt with a per-pair lower bound before that point.

## Weekly / monthly rollups

`fact_demand_weekly` / `fact_demand_monthly` are simple `group by` queries over `fact_demand_daily` — never touching `fct_sales` again, satisfying the "aggregate without reprocessing raw source data" requirement (this is exactly how Deliverable 3's weekly/monthly series were produced). Boundaries, used consistently by both the rollups and Deliverable 3's Seasonal Naive alignment:
- **Week = ISO week starting Monday** (`date_trunc('week', date_day)` in Spark SQL, which is Monday-anchored), labeled by its Monday date.
- **Month = calendar month** (`date_trunc('month', date_day)`, i.e. `month_start` from `dim_calendary`).

## Model-input / feature layer (sketch only — not built this phase)

A logically separate `demand_features` layer sitting on top of `fact_demand_daily`, kept in its own schema/location so Delta versioning can distinguish "recomputed source-of-truth" from "regenerated feature set." Reserved column groups for Phase 2, added incrementally without changing `fact_demand_daily`'s shape:
- **Calendar/holiday** — `dim_calendary` currently has no holiday flags at all; this needs to be added (to `dim_calendary` itself, or as a feature-layer join) before Phase 2 can use it.
- **Weather, economic indicators, promotions** — no source data for any of these exists in the current bronze/marts layer; all would need new ingestion.
- **Inventory-derived features** — lead time from `product_suppliers.lead_time_days` (bronze-only, not yet in any mart), stockout flags (already sketched above, pending the stock-data caveat being resolved).

## Open questions for the team

1. **No store-to-serving-DC mapping exists in the source data.** `stock_movements.movement_type` has exactly 4 values (`purchase_in`, `sale_out`, `return_in`, `return_out`) — no "transfer" type — so inventory flow between locations (e.g. a warehouse restocking a store) is invisible in the current model. This blocks the later "assess whether new DCs are needed" business goal. Needs a decision: proceed without it, or go back to the source system for a transfer/replenishment table.
2. **`location_type` is resolved, but with an unexpected twist.** It's a clean 3 store / 3 warehouse split (verified in `01_data_exploration_summary.md` §2) — but warehouses generate almost exactly as much direct sales volume as stores (both `ecommerce` and `pos` channels). This complicates "product x **store**" as literally stated in Task 1.1: should warehouse-attributed sales count toward the forecasting unit, or does `location_id` on an order mean "fulfilling location" rather than "storefront," in which case the unit should perhaps be "product x fulfilling-location" regardless of type? **Needs a team decision before Task 1.1 is finalized** — this schema currently includes both types undifferentiated.
3. **Gross vs. net demand as the forecasting target.** This proposal keeps both `qty_sold_gross` and `qty_sold_net` (net of returns) as separate columns and defers the choice of which one Phase 2/3 should target.
4. **`dim_locations` SCD2 join uses the current/latest version only**, not a temporal "valid as of the transaction date" join — added complexity that isn't justified yet, since the dev data currently has exactly one row per `location_id` (no historical versions have been generated). Revisit if/when real location history accumulates.
5. **`reorder_point`** exists in bronze `stock_levels` but is dropped in staging (`stg_stock_levels`) — flagged as a possible useful re-addition for Phase 2's inventory features, explicitly not done as a drive-by change here.
6. **No 2020-2021 COVID-era anomaly was found** (Deliverable 1 §3) — no adjustment needed in the training window.
7. **Stock/censored-demand columns — partially resolved.** The future-dating half of this problem is fixed as of the develop merge (`fct_daily_stock_levels` is now 0% future-dated, down from 77% — see Deliverable 1 §4). The sparse-history half is **not** resolved and was never a future-dating issue: the non-future portion still has essentially no time-series depth (~1.2 snapshots per pair). `stock_on_hand`, `is_stockout_day`, and `is_demand_censored_flag` are now computed from clean data, but should still not be trusted for confident analysis until stock history has real density — via denser source snapshots or a `stock_movements`-derived running balance (team's own reconciliation test already flags that movements and snapshots don't always agree).
