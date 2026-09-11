-- Macro: convert_currency
-- Purpose: Converts an amount between BRL and USD using an exchange rate column.

{% macro convert_currency(amount_column, currency_column, exchange_rate_column, target_currency='BRL') %}
    case
        -- Source currency already matches the target (e.g. BRL ->  BRL): keep the amount
        when {{ currency_column }} = '{{ target_currency }}' then {{ amount_column }}
        
        -- USD to BRL: multiply by the exchange rate
        when {{ currency_column }} = 'USD' and '{{ target_currency }}' = 'BRL' 
            then {{ amount_column }} * {{ exchange_rate_column }}
            
        -- BRL to USD: divide by the exchange rate
        when {{ currency_column }} = 'BRL' and '{{ target_currency }}' = 'USD' 
            then {{ amount_column }} / nullif({{ exchange_rate_column }}, 0)
            
        -- Fallback: keep the original amount for any unmapped currency pair
        else {{ amount_column }}
    end
{% endmacro %}