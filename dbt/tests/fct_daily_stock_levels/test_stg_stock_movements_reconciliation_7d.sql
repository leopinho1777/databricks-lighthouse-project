{{ config(severity='warn') }}

-- Base de movimentos dos ultimos 7 dias.
-- A quantidade e normalizada para absoluto e o sinal e reaplicado por movement_type mais adiante.
with movement_base as (

    select
        stock_movement_id,
        cast(occurred_at as date) as stock_day,
        product_variant_id,
        location_id,
        movement_type,
        cast(quantity as integer) as quantity,
        is_zero_quantity_movement,
        abs(cast(quantity as integer)) as quantity_abs
    from {{ ref('stg_stock_movements') }}
    where cast(occurred_at as date) >= date_sub(current_date(), 7)

),

-- Delta diario esperado por produto/local a partir dos movimentos.
movement_daily as (

    select
        stock_day,
        product_variant_id,
        location_id,
        sum(
            case
                when movement_type in ('purchase_in', 'return_in') then quantity_abs
                when movement_type in ('sale_out', 'return_out') then -quantity_abs
                else 0
            end
        ) as net_movement_expected
    from movement_base
    group by 1, 2, 3

),

-- Movimentos com quantidade zero devem ser revisados, mesmo sem impacto liquido no estoque.
zero_quantity_review as (

    select
        stock_movement_id,
        stock_day,
        product_variant_id,
        location_id,
        movement_type,
        quantity,
        cast(null as integer) as opening_stock_snapshot,
        cast(null as integer) as net_movement_expected,
        cast(null as integer) as closing_stock_expected,
        cast(null as integer) as closing_stock_snapshot,
        cast(null as integer) as delta_diff,
        'zero_quantity_movement_review' as mismatch_category,
        cast(null as double) as unknown_ratio_day,
        true as is_zero_quantity_movement
    from movement_base
    where is_zero_quantity_movement

),

-- Snapshot diario bruto: pode haver mais de um registro no mesmo dia/chave.
-- Mantemos apenas o mais recente com row_number no proximo CTE.
snapshot_daily_source as (

    select
        cast(dbt_valid_from as date) as stock_day,
        product_variant_id,
        location_id,
        cast(quantity_on_hand as integer) as closing_stock_snapshot,
        cast(dbt_valid_from as timestamp) as snapshot_valid_from,
        row_number() over (
            partition by cast(dbt_valid_from as date), product_variant_id, location_id
            order by cast(dbt_valid_from as timestamp) desc
        ) as row_num
    from {{ ref('snap_stock_levels') }}
    where dbt_valid_from is not null
      and cast(dbt_valid_from as date) >= date_sub(current_date(), 8)

),

-- Snapshot diario consolidado (ultimo registro do dia por produto/local).
snapshot_daily as (

    select
        stock_day,
        product_variant_id,
        location_id,
        closing_stock_snapshot,
        snapshot_valid_from
    from snapshot_daily_source
    where row_num = 1

),

-- Calcula saldo de abertura como o saldo de fechamento do dia anterior.
snapshot_with_opening as (

    select
        stock_day,
        product_variant_id,
        location_id,
        closing_stock_snapshot,
        snapshot_valid_from,
        lag(closing_stock_snapshot) over (
            partition by product_variant_id, location_id
            order by stock_day
        ) as opening_stock_snapshot
    from snapshot_daily

),

-- Reconcilia movimentos e snapshot por full outer join para capturar pares faltantes.
-- Regras de categorizacao:
-- - movement_without_snapshot_net_zero: permitido (movimento liquido zero no dia)
-- - missing_snapshot_for_nonzero_movement: divergencia
-- - snapshot_without_movement: divergencia de processo
-- - missing_opening_snapshot: sem base para fechar conta no primeiro dia da serie
-- - value_mismatch: fechamento diferente do esperado
recon_universe as (

    select
        cast(null as string) as stock_movement_id,
        coalesce(m.stock_day, s.stock_day) as stock_day,
        coalesce(m.product_variant_id, s.product_variant_id) as product_variant_id,
        coalesce(m.location_id, s.location_id) as location_id,
        cast(null as string) as movement_type,
        cast(null as integer) as quantity,
        s.opening_stock_snapshot,
        m.net_movement_expected,
        case
            when s.opening_stock_snapshot is not null then s.opening_stock_snapshot + coalesce(m.net_movement_expected, 0)
        end as closing_stock_expected,
        s.closing_stock_snapshot,
        case
            when s.opening_stock_snapshot is not null and s.closing_stock_snapshot is not null
                then s.closing_stock_snapshot - (s.opening_stock_snapshot + coalesce(m.net_movement_expected, 0))
        end as delta_diff,
        case
            when s.stock_day is null and coalesce(m.net_movement_expected, 0) = 0 then 'movement_without_snapshot_net_zero'
            when s.stock_day is null then 'missing_snapshot_for_nonzero_movement'
            when m.stock_day is null then 'snapshot_without_movement'
            when s.opening_stock_snapshot is null then 'missing_opening_snapshot'
            when s.closing_stock_snapshot <> (s.opening_stock_snapshot + coalesce(m.net_movement_expected, 0)) then 'value_mismatch'
            else 'ok'
        end as mismatch_category,
        case
            when m.stock_day is null or s.stock_day is null then 1
            else 0
        end as unknown_pairing_flag,
        false as is_zero_quantity_movement
    from movement_daily as m
    full outer join snapshot_with_opening as s
      on m.stock_day = s.stock_day
     and m.product_variant_id = s.product_variant_id
     and m.location_id = s.location_id
    where coalesce(m.stock_day, s.stock_day) >= date_sub(current_date(), 7)

),

-- Mede a proporcao diaria de pares faltantes (unknown de pareamento).
unknown_ratio_by_day as (

    select
        stock_day,
        cast(sum(unknown_pairing_flag) as double) / nullif(cast(count(*) as double), 0) as unknown_ratio_day
    from recon_universe
    group by 1

),

-- Projecao final com campos de observabilidade para triagem.
final as (

    select
        r.stock_day,
        r.stock_movement_id,
        r.product_variant_id,
        r.location_id,
        r.movement_type,
        r.quantity,
        r.opening_stock_snapshot,
        r.net_movement_expected,
        r.closing_stock_expected,
        r.closing_stock_snapshot,
        r.delta_diff,
        r.mismatch_category,
        u.unknown_ratio_day,
        r.is_zero_quantity_movement
    from recon_universe as r
    left join unknown_ratio_by_day as u
      on r.stock_day = u.stock_day

    union all

    select
        z.stock_day,
        z.stock_movement_id,
        z.product_variant_id,
        z.location_id,
        z.movement_type,
        z.quantity,
        z.opening_stock_snapshot,
        z.net_movement_expected,
        z.closing_stock_expected,
        z.closing_stock_snapshot,
        z.delta_diff,
        z.mismatch_category,
        z.unknown_ratio_day,
        z.is_zero_quantity_movement
    from zero_quantity_review as z

)

-- O teste retorna apenas categorias que devem alertar/falhar a regra principal.
select *
from final
where mismatch_category in (
    'zero_quantity_movement_review',
    'missing_snapshot_for_nonzero_movement',
    'snapshot_without_movement',
    'value_mismatch'
)
