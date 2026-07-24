{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}

    {# 1. Se não houver schema customizado, usa a schema padrão do dev #}
    {%- if custom_schema_name is none -%}

        {{ default_schema }}

    {# 2. Para qualquer camada (staging, intermediate, marts), junta a schema do dev + sufixo da camada #}
    {%- else -%}

        {{ default_schema }}_{{ custom_schema_name | trim }}

    {%- endif -%}

{%- endmacro %}