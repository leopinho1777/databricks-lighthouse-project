with fct_sales as (

    select * from {{ ref('fct_sales') }}

),

daily_metrics as (

    select
        -- Table grain: Day and Channel
        date_id,
        channel,
        
        -- Gross Revenue (Excluding canceled orders)
        sum(
            case 
                when order_status != 'canceled' then line_total 
                else 0 
            end
        ) as gross_revenue,
        
        -- Valid Orders Volume
        count(distinct 
            case 
                when order_status != 'canceled' then order_id 
            end
        ) as valid_orders_volume,
        
        -- Canceled Orders Volume (For Cancellation Rate as per decision D2)
        count(distinct 
            case 
                when order_status = 'canceled' then order_id 
            end
        ) as canceled_orders_volume,

        -- Total Items Volume (For Average Basket Size / Items per Order)
        count(
            case 
                when order_status != 'canceled' then order_item_id 
            end
        ) as valid_items_volume

    from fct_sales
    group by 1, 2

)

select * from daily_metrics