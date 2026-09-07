# Data Exploration Summary — Demand Forecasting Phase 1

Explores the live dev marts (`develop.eros_analytics_marts`, via `~/.dbt/profiles.yml`) to ground Task 1.1/1.2/1.5 in real evidence rather than assumptions about the transformation layer. Numbers below were produced by [`explore_marts.py`](explore_marts.py); raw query outputs are in [`output/`](output/). Re-run the script after any dbt rebuild to refresh these numbers.

## 1. Table inventory

| table | grain | rows | date range | notes |
|---|---|---|---|---|
| `fct_sales` | 1 row per order line item | 137,271 | 2020-01-01 to 2026-08-14 | 0% null on `placed_at`/`product_variant_id`/`location_id`/`quantity`/`unit_price`; 0 duplicate `order_item_id`; 0 rows hit the `19000101` sentinel date. Very clean at the mart level — the dbt-layer dedup/required-column/future-date filters are doing their job. |
| `dim_products` | 1 row per product variant (SKU) | 1,009 | n/a | 0% null on `sale_price`/`cost_price`/`category_name`; 18 products (1.8%) fall into `category_name = 'Não Classificado'`. |
| `dim_locations` | SCD2, 1 row per location version | 6 | n/a | Only 6 physical locations total, each with exactly one row currently (no multi-version history yet present) — see §2. |
| `dim_calendary` | 1 row per calendar day | 2,423 | 2020-01-01 to ~2026 | Dense spine as documented, no gaps by construction. |
| `fct_daily_stock_levels` | sparse, 1 row per stock-change day x product x location | 6,054 | **2023-11-27 to 2027-01-27** | See §4 — most of this range is fabricated/future-dated. |
| `fct_returns` | 1 row per returned item | 1,304 | n/a | Not deeply profiled this pass; low volume relative to sales. |

`order_status` split on `fct_sales`: `paid` 96,358 · `confirmed` 20,703 · `cancelled` 13,486 · `draft` 6,724. Only paid+confirmed (117,061 rows, 85%) count as valid revenue.

## 2. `location_type` — resolves the store-vs-DC open question

All 6 locations are active, and the split is exactly 3 stores / 3 warehouses, cleanly typed (no ambiguous/missing `location_type` values):

| location_id | name | type |
|---|---|---|
| 1 | Loja Leão | store |
| 5 | Loja Oliveira | store |
| 6 | Loja Mendonça | store |
| 2 | Armazém Camargo | warehouse |
| 3 | Armazém Siqueira | warehouse |
| 4 | Armazém Novaes | warehouse |

**Unexpected finding:** warehouses generate almost exactly as much sales volume as stores — 68,827 order-item rows / 378,081 units at warehouses vs. 68,444 rows / 376,585 units at stores, split near-identically across both `ecommerce` and `pos` channels at each type. This contradicts the usual mental model of "warehouses replenish stores which sell to customers" — here, warehouse `location_id`s are attributed roughly half of all direct sales, including in-person (`pos`) sales. **Open question for the team:** does `orders.location_id` really mean "location that fulfilled/processed this order" for e-commerce (in which case a warehouse being the fulfillment location makes sense), while only `pos` sales should map to "true" storefronts? If so, `pos` sales at warehouse locations (20,473 rows) would need a second look — either they're legitimate wholesale/counter sales at a warehouse, or a mock-data artifact worth flagging back to the source. This matters directly for Task 1.1 (what counts as "store" for the forecasting unit).

## 3. 2020-2021 anomaly check — no COVID-era anomaly found

Annual revenue growth is remarkably stable and monotonic, with no dip or spike around 2020-2021:

| year | valid orders | valid qty | gross revenue | YoY % |
|---|---|---|---|---|
| 2020 | 3,881 | 64,571 | R$113.8M | — |
| 2021 | 4,405 | 73,006 | R$129.8M | **+14.0%** |
| 2022 | 5,073 | 84,014 | R$149.8M | +15.4% |
| 2023 | 5,783 | 95,953 | R$171.0M | +14.2% |
| 2024 | 6,634 | 110,039 | R$195.5M | +14.4% |
| 2025 | 7,845 | 128,775 | R$228.9M | +17.1% |
| 2026* | 5,259 | 87,350 | R$154.3M | n/a (partial year) |

A like-for-like Jan-Aug comparison (so the partial 2026 year is comparable) confirms the same pattern — growth in the +12% to +16% band every single year, including 2020→2021, with 2026 slightly lower at +9.4% but still solidly positive (`output/jan_aug_comparable_totals.csv`).

**Verdict: no 2020-2021 anomaly to correct for.** This is mock/synthetic data and does not encode the real-world COVID disruption the business risk description anticipated — growth looks like a smooth, designed trend line rather than an organic series. Do not build COVID-adjustment logic into the baseline models; there's nothing here to adjust for.

Within-year seasonality is strong and consistent every year: peak Dec-Mar, trough Jun-Aug (visible in `output/monthly_sales_by_year.csv`). This matches Brazil's Southern Hemisphere summer (Dec-Mar) being the high season for a nautical/boating retailer — a sensible, usable seasonal signal for Seasonal Naive.

## 4. Censored-demand check — inconclusive, and the stock data itself is a bigger problem

Two findings, both important for the schema design (§ open questions in Deliverable 2):

**a) Most of `fct_daily_stock_levels` is future-dated mock data.** 4,679 of 6,054 rows (77%) fall after today (2026-09-07), extending out to 2027-01-27. Unlike `fct_sales` — which explicitly filters future-dated rows via `stg_orders.sql` — nothing in the stock pipeline does the same. This is a real gap worth raising with the team/back to the source: stock-level history should get the same future-date filtering `fct_sales` already has.

**b) The non-future stock history is far too sparse to support a real censored-demand analysis.** Restricting to the 1,375 non-future rows, every one of them is the *only* stock observation for its (product, location) pair — i.e., there is no actual daily change history in the usable range, just one scattered point-in-time snapshot per pair between 2023-11-27 and today. "Forward-filling" this is really just carrying forward a single stale number, possibly for years, across an unknown number of real (but unrecorded) restocks in between.

Running the mechanical check anyway (sold qty on/after the snapshot date vs. that snapshot's quantity): 1,341 of 1,364 comparable observations (98.3%) show `qty_sold >= stock_on_hand`. **Do not read this as "98% of demand is censored"** — with only one stale snapshot per pair, this number mostly reflects snapshot staleness, not real stockouts. The honest answer to "does censored demand exist?" is: **we can't tell from the current data.** Resolving it needs either (a) `stock_movements`-derived running balances (which the team's own reconciliation test already flags as not always trustworthy — see `test_stg_stock_movements_reconciliation_7d.sql`) or (b) denser, non-future-dated stock snapshots than currently exist.

## 5. Summary of flags for the team

1. **Warehouse locations generate ~half of all direct sales** (including POS), which doesn't match the usual store-vs-DC mental model — needs a decision before "product x store" (Task 1.1) is finalized. See §2.
2. **No 2020-2021 anomaly** — don't build correction logic for it.
3. **Stock-level data has two compounding problems**: 77% future-dated rows, and the non-future portion has essentially no time-series depth (one snapshot per pair). The censored-demand question stays open.
4. **No store-to-serving-DC mapping exists anywhere in the source data** (confirmed separately during schema design, Deliverable 2) — `stock_movements.movement_type` has no "transfer" type, so inventory flow between locations is invisible. Relevant to the later "assess new DC need" business goal.
