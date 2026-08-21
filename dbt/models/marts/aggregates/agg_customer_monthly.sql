with fct_sales as (

    select
        customer_id,
        order_id,
        line_total,
        placed_at,
        order_status
    from {{ ref('fct_sales') }}

),

customers as (

    select
        customer_id,
        person_type
    from {{ ref('dim_customers') }}

),

calendary as (

    select distinct
        month_start
    from {{ ref('dim_calendary') }}
    -- Filtramos para não criar linhas de meses futuros no BI
    where month_start <= trunc(current_date(), 'MM')
      and year > 1900 -- Remove a data dummy (1900-01-01)[cite: 8]

),

customer_first_purchase as (

    -- Descobrimos quando a "vida" do cliente começou para não criar meses zerados antes dele existir
    select 
        customer_id,
        min(trunc(cast(placed_at as date), 'MM')) as first_active_month
    from fct_sales
    where order_status in ('paid', 'confirmed') -- Apenas receita válida
    group by 1

),

customer_spine as (

    -- Criamos a matriz perfeita: Cliente x Todos os meses desde a sua primeira compra
    select
        c.customer_id,
        c.person_type,
        cal.month_start as reporting_month
    from customer_first_purchase as cfp
    left join customers as c 
        on cfp.customer_id = c.customer_id
    cross join calendary as cal
    where cal.month_start >= cfp.first_active_month

),

sales_monthly_aggs as (

    -- Agregamos as vendas reais do cliente mês a mês
    select
        customer_id,
        trunc(cast(placed_at as date), 'MM') as active_month,
        count(distinct order_id) as total_valid_orders,
        sum(line_total) as monthly_revenue,
        max(placed_at) as last_purchase_at
    from fct_sales
    where order_status in ('paid', 'confirmed') -- Apenas receita válida[cite: 4]
    group by 1, 2

),

final as (

    -- Unimos a matriz com as vendas reais. Onde não houver venda, o COALESCE coloca zero.
    select
        {{ dbt_utils.generate_surrogate_key(['spine.customer_id', 'spine.reporting_month']) }} as customer_monthly_sk,
        spine.customer_id,
        spine.person_type,
        spine.reporting_month,
        coalesce(sales.total_valid_orders, 0) as total_valid_orders,
        coalesce(sales.monthly_revenue, 0) as monthly_revenue,
        sales.last_purchase_at
    from customer_spine as spine
    left join sales_monthly_aggs as sales
        on spine.customer_id = sales.customer_id
        and spine.reporting_month = sales.active_month

)

select * from final