-- Exploratory prototype for `fact_demand_daily`, described in 02_ideal_schema_proposal.md.
-- NOT a dbt model. Lives in each developer's own scratch schema, disposable/rebuildable at will.
-- {marts}/{scratch_schema} are filled in by build_prototype.py -- see
-- _shared/db_connection.py's data source convention (PROD_MARTS, get_scratch_schema()).
-- Run via: uv run python forecasting/02_schema_design/build_prototype.py

create or replace table {scratch_schema}.fact_demand_daily as

-- Every (product, location) pair that has ever transacted or held a stock record.
-- In the current dev data this equals the full dim_products x dim_locations cross
-- join (every one of 1,009 products has sold at all 6 locations) — but the
-- "ever transacted" filter is kept so the logic stays correct if that changes
-- (e.g. a newly onboarded product that hasn't sold everywhere yet).
with pairs as (
    select distinct product_variant_id, location_id
    from {marts}.fct_sales
    union
    select distinct product_variant_id, location_id
    from {marts}.fct_daily_stock_levels
),

-- Dense daily spine bounded to the actual sales history, excluding the
-- current (incomplete) day.
date_bounds as (
    select
        min(date(placed_at)) as min_day,
        date_sub(current_date(), 1) as max_day
    from {marts}.fct_sales
),

spine as (
    select p.product_variant_id, p.location_id, c.date_id, c.date_day
    from pairs p
    cross join {marts}.dim_calendary c
    cross join date_bounds b
    where c.date_day between b.min_day and b.max_day
),

-- Gross demand: valid orders only (paid/confirmed), attributed to the sale's
-- own date/location — matches the "valid revenue" convention already used by
-- agg_sales_daily / agg_product_performance.
sales_daily as (
    select
        product_variant_id,
        location_id,
        date_id,
        sum(quantity) as qty_sold_gross,
        sum(line_total) as revenue_gross
    from {marts}.fct_sales
    where order_status in ('paid', 'confirmed')
    group by 1, 2, 3
),

-- Returns netted back onto the ORIGINAL sale's date/location/product (via the
-- order_item_id bridge), consistent with how agg_sales_daily nets returns
-- against the original sale month rather than the return date.
returns_by_original_sale as (
    select
        s.product_variant_id,
        s.location_id,
        s.date_id,
        sum(r.quantity) as qty_returned,
        sum(r.refund_amount) as refund_amount
    from {marts}.fct_returns r
    inner join {marts}.fct_sales s
        on r.order_item_id = s.order_item_id
    group by 1, 2, 3
),

-- Location type, current version only. dim_locations is SCD2, but the dev
-- data currently has exactly one row per location_id (no historical versions
-- yet) — see open question #4 in 02_ideal_schema_proposal.md on whether a
-- temporal (valid-as-of-transaction-date) join is worth the added complexity
-- once real location history exists.
locations_current as (
    select location_id, location_type
    from {marts}.dim_locations
    qualify row_number() over (partition by location_id order by updated_at desc) = 1
),

-- Stock on hand, forward-filled per (product, location), restricted to
-- non-future snapshot dates. CAVEAT (see 01_data_exploration_summary.md §4):
-- in the current data this is functionally a single stale point-in-time
-- snapshot per pair, not a real time series, and the resulting
-- is_demand_censored_flag below should be treated as unreliable until the
-- source stock data has real density.
stock_history as (
    select
        product_variant_id,
        location_id,
        stock_level_day,
        physical_quantity_on_hand
    from {marts}.fct_daily_stock_levels
    where stock_level_day <= current_date()
),

stock_filled as (
    select
        sp.product_variant_id,
        sp.location_id,
        sp.date_day,
        last_value(sh.physical_quantity_on_hand, true) over (
            partition by sp.product_variant_id, sp.location_id
            order by sp.date_day
            rows between unbounded preceding and current row
        ) as stock_on_hand
    from spine sp
    left join stock_history sh
        on sp.product_variant_id = sh.product_variant_id
        and sp.location_id = sh.location_id
        and sp.date_day = sh.stock_level_day
)

select
    sp.date_id,
    sp.date_day,
    sp.product_variant_id,
    sp.location_id,
    lc.location_type,
    coalesce(sd.qty_sold_gross, 0) as qty_sold_gross,
    coalesce(rt.qty_returned, 0) as qty_returned,
    coalesce(sd.qty_sold_gross, 0) - coalesce(rt.qty_returned, 0) as qty_sold_net,
    coalesce(sd.revenue_gross, 0) - coalesce(rt.refund_amount, 0) as revenue_net,
    sf.stock_on_hand,
    sf.stock_on_hand = 0 as is_stockout_day,
    -- Heuristic only — see stock_history caveat above.
    coalesce(sd.qty_sold_gross, 0) >= sf.stock_on_hand as is_demand_censored_flag,
    current_timestamp() as source_built_at
from spine sp
left join sales_daily sd
    on sp.product_variant_id = sd.product_variant_id
    and sp.location_id = sd.location_id
    and sp.date_id = sd.date_id
left join returns_by_original_sale rt
    on sp.product_variant_id = rt.product_variant_id
    and sp.location_id = rt.location_id
    and sp.date_id = rt.date_id
left join locations_current lc
    on sp.location_id = lc.location_id
left join stock_filled sf
    on sp.product_variant_id = sf.product_variant_id
    and sp.location_id = sf.location_id
    and sp.date_day = sf.date_day
