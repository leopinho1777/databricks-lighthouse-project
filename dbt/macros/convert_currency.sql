{% macro convert_currency(amount_column, currency_column, exchange_rate_column, target_currency='BRL') %}
    case
        -- Se a moeda original já for a moeda alvo (ex: BRL -> BRL), mantém o valor
        when {{ currency_column }} = '{{ target_currency }}' then {{ amount_column }}
        
        -- Se a moeda for USD e o destino BRL, multiplica pela taxa
        when {{ currency_column }} = 'USD' and '{{ target_currency }}' = 'BRL' 
            then {{ amount_column }} * {{ exchange_rate_column }}
            
        -- Se a moeda for BRL e o destino USD, divide pela taxa
        when {{ currency_column }} = 'BRL' and '{{ target_currency }}' = 'USD' 
            then {{ amount_column }} / nullif({{ exchange_rate_column }}, 0)
            
        -- Fallback: mantém o valor original se for uma combinação não mapeada
        else {{ amount_column }}
    end
{% endmacro %}