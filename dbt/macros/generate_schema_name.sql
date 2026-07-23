{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}

    {# 1. Se não houver schema customizado configurado, usa a schema padrão do dev #}
    {%- if custom_schema_name is none -%}

        {{ default_schema }}

    {# 2. Se for STAGING: adiciona o sufixo _staging na schema individual do dev #}
    {%- elif custom_schema_name == 'staging' -%}

        {{ default_schema }}_staging

    {# 3. Se for INTERMEDIATE, MARTS ou outra camada: usa a schema exata (compartilhada) #}
    {%- else -%}

        {{ custom_schema_name | trim }}

    {%- endif -%}

{%- endmacro %}