with source as (

    select * from {{ source('bronze', 'raw_exchange_rates') }}

),

date_spine as (

    select explode(sequence(
        (select min(exchange_date) from source),
        current_date(),
        interval 1 day
    )) as exchange_date

),

joined as (

    select
        d.exchange_date,
        coalesce(s.currency_from, 'USD') as currency_from,
        coalesce(s.currency_to, 'BRL') as currency_to,
        s.exchange_rate
    from date_spine d
    left join source s
        on d.exchange_date = s.exchange_date

),

filled as (

    select
        exchange_date,
        currency_from,
        currency_to,
        last_value(exchange_rate, true) over (
            order by exchange_date
            rows between unbounded preceding and current row
        ) as exchange_rate
    from joined

)

select
    exchange_date,
    currency_from,
    currency_to,
    cast(exchange_rate as numeric(10,4)) as exchange_rate
from filled