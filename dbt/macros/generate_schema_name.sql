{#
  El contrato exige el esquema exacto `mart_logistica`. Por defecto dbt
  antepone el esquema del target (`main_mart_logistica`); aquí el esquema
  configurado se usa tal cual.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
