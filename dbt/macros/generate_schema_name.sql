{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}

    {# Dev: append layer suffix to user schema (leonardo_zoot_analytics_staging) #}
    {# Prod: use layer name as schema (staging, intermediate, marts) #}
    
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    
    {%- elif target.name == 'prod' -%}
        {# Production: use the custom schema name directly #}
        {{ custom_schema_name | trim }}
    
    {%- else -%}
        {# Development: append to default schema #}
        {{ default_schema }}_{{ custom_schema_name | trim }}
    
    {%- endif -%}

{%- endmacro %}