# Data Exploration Summary — Demand Forecasting Phase 1

> **Updated after develop merge on 2026-09-11.** `develop` now includes the future-date filtering fix (`filter_future_dated()` macro, applied to `stg_stock_levels`/`stg_stock_movements`/etc.), and `fct_daily_stock_levels` has been rebuilt (`--full-refresh`) against the corrected snapshot. §1 and §4 below are refreshed with the real post-fix numbers — everything else (sales data, the 2020-2021 anomaly check) was unaffected by this fix and is unchanged. See the "Updated" callouts inline for what changed and what didn't.

Explores the stable prod marts (`lh_nautical.marts`, via `~/.dbt/profiles.yml` — see `../README.md`'s "Data source convention") to ground Task 1.1/1.2/1.5 in real evidence rather than assumptions about the transformation layer. Numbers below were produced by [`explore_marts.py`](explore_marts.py); raw query outputs are in [`output/`](output/). Re-run the script after any dbt rebuild to refresh these numbers.

## 1. Table inventory

| table | grain | rows | date range | notes |
|---|---|---|---|---|
| `fct_sales` | 1 row per order line item | 137,271 | 2020-01-01 to 2026-08-14 | 0% null on `placed_at`/`product_variant_id`/`location_id`/`quantity`/`unit_price`; 0 duplicate `order_item_id`; 0 rows hit the `19000101` sentinel date. Very clean at the mart level — the dbt-layer dedup/required-column/future-date filters are doing their job. |
| `dim_products` | 1 row per product variant (SKU) | 1,009 | n/a | 0% null on `sale_price`/`cost_price`/`category_name`; 18 products (1.8%) fall into `category_name = 'Não Classificado'`. |
| `dim_locations` | SCD2, 1 row per location version | 6 | n/a | Only 6 physical locations total, each with exactly one row currently (no multi-version history yet present) — see §2. |
| `dim_calendary` | 1 row per calendar day | 2,423 | 2020-01-01 to ~2026 | Dense spine as documented, no gaps by construction. |
| `fct_daily_stock_levels` | sparse, 1 row per stock-change day x product x location | ~~6,054~~ **1,413** | ~~2023-11-27 to 2027-01-27~~ **2023-11-27 to 2026-09-11** | **Updated:** future-date filter fix now live and the mart rebuilt — 0% future-dated (was 77%). See §4. Distinct products with any real stock history dropped from 1,009 to 802 — ~207 products only ever appeared here via now-removed fabricated future rows, meaning they have no genuine stock history at all. |
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

## 4. Censored-demand check — updated post-fix: cleaner data, same fundamental limitation

> **Updated after develop merge.** The future-date bug (finding "a" below) is now fixed and verified. Finding "b" (sparse stock history) is **not** resolved by this fix — it was never a future-dating problem, it's a genuine data-density limitation. Both are re-run below with real post-fix numbers.

**a) [RESOLVED] Future-dated mock data.** Before the fix: 4,669 of 6,054 rows (77%) fell after "today", extending out to 2027-01-27. After the fix (`filter_future_dated()` applied to `stg_stock_levels.updated_at`, snapshot rebuilt, mart full-refreshed): **0 of 1,413 rows are future-dated.** Verified directly (`future_dated_stock_rows.csv`), not assumed. `fct_sales` was never affected by this bug (it already had its own filter) and needed no change.

**b) [STILL OPEN] The non-future stock history remains too sparse for a confident censored-demand read — a different, unrelated problem.** Re-running the same check post-fix: 1,608 comparable observations across 1,342 distinct (product, location) pairs (up from 1,364 / 1,142 pre-fix — a genuine ~17-18% increase in usable pairs now that fabricated noise is gone) — but the ratio is still ~1.2 observations per pair, i.e. **still essentially one snapshot per pair**, not a real time series. Removing fabricated future rows cleaned up *what* data exists; it didn't create more of it. The mechanical check gives **98.2% flagged** (1,579 of 1,608) — statistically unchanged from the pre-fix 98.3%, exactly as expected, since this check was never measuring the future-date bug in the first place.

**New evidence this pass:** the built `fact_demand_daily` prototype forward-fills each pair's single snapshot across its *entire* dense date range (not just the day of/after the snapshot, which is what the check above does). Over the full 14.8M-row table, only 187,174 rows (1.3%) have any known `stock_on_hand` value at all (the rest predate any snapshot for that pair). Of those: **0.12% are stockout days, 0.95% are flagged demand-censored** — a much lower, more believable rate than the naive 98% figure. The gap between these two numbers is itself informative: the 98% figure is an artifact of the check's sampling (it only compares right at/after the one snapshot date, precisely when a burst of sales is most likely to look large relative to "current" stock); the dense full-table view, averaged over years, tells a calmer story. Neither number should be treated as a confident measurement — both rest on the same one-snapshot-per-pair limitation — but the dense view is the more defensible of the two if a single number is needed.

**Revised honest answer:** the future-dating bug is fixed and confirmed not to be the source of the censored-demand ambiguity. The real blocker — stock history depth — is unchanged by this fix and remains open. Resolving it still needs either (a) `stock_movements`-derived running balances (team's own reconciliation test already flags these as not always trustworthy — see `test_stg_stock_movements_reconciliation_7d.sql`) or (b) genuinely denser stock snapshots than the source system currently produces.

## 5. Summary of flags for the team

1. **Warehouse locations generate ~half of all direct sales** (including POS), which doesn't match the usual store-vs-DC mental model — needs a decision before "product x store" (Task 1.1) is finalized. See §2.
2. **No 2020-2021 anomaly** — don't build correction logic for it.
3. **Stock-level data had two compounding problems — one is now fixed, one remains.** The 77%-future-dated-rows problem is resolved (0% as of the develop merge). The non-future portion still has essentially no time-series depth (~1.2 snapshots per pair) — this was never a future-dating issue, so the fix didn't touch it. The censored-demand question stays open for this reason alone.
4. **No store-to-serving-DC mapping exists anywhere in the source data** (confirmed separately during schema design, Deliverable 2) — `stock_movements.movement_type` has no "transfer" type, so inventory flow between locations is invisible. Relevant to the later "assess new DC need" business goal.
5. **`dim_locations.city_name` is Faker-generated mock data, not real places** (discovered during Stage 2 feature engineering, task 2.4, when sourcing external weather data for `04_weather` — city names like "Barbosa do Sul" and "Cavalcanti da Mata" aren't real, geocodable Brazilian cities). `state_code` values ARE real Brazilian states. Same category of issue as findings #2/#3 above (mock data doesn't always behave like real data) — any future work joining `dim_locations` to an external city-level dataset should geocode/join by `state_code`, not `city_name`. Worked around in `04_weather` via a state-capital coordinate lookup rather than per-city geocoding.
