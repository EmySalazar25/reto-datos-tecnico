{#
  Deduplicación de la réplica Airbyte CDC.

  Cada fila de landing es una versión de un registro. El orden real de los cambios lo da el
  LSN de SQL Server: `_ab_cdc_updated_at` puede empatar entre versiones distintas del mismo
  registro, y el orden de llegada no es confiable. Desempates, en orden:
    1. `_ab_cdc_lsn` (numérico, mayor = más reciente)
    2. `_ab_cdc_updated_at`
    3. `_dp_ingerido_en` (la entrega más reciente)

  La llave primaria se toma de `meta.primary_key` de la fuente: no se repite en cada modelo.
#}

{% macro llave_fuente(source_name, table_name) -%}
    {%- if execute -%}
        {%- set matches = graph.sources.values()
            | selectattr('source_name', 'equalto', source_name)
            | selectattr('name', 'equalto', table_name) | list -%}
        {%- if matches | length != 1 -%}
            {{ exceptions.raise_compiler_error('fuente no declarada: ' ~ source_name ~ '.' ~ table_name) }}
        {%- endif -%}
        {%- set pk = matches[0].config.meta.get('primary_key') or matches[0].meta.get('primary_key') -%}
        {%- if not pk -%}
            {{ exceptions.raise_compiler_error(source_name ~ '.' ~ table_name ~ ' no declara meta.primary_key') }}
        {%- endif -%}
        {{ return(pk) }}
    {%- else -%}
        {{ return(['1']) }}
    {%- endif -%}
{%- endmacro %}

{% macro cdc_orden() -%}
    {{ dbt.safe_cast('_ab_cdc_lsn', dbt.type_numeric()) }} desc nulls last,
    {{ dbt.safe_cast('_ab_cdc_updated_at', dbt.type_timestamp()) }} desc nulls last,
    _dp_ingerido_en desc
{%- endmacro %}

{#
  Estado actual: la versión más reciente de cada llave. Si esa versión es un borrado, la llave
  desaparece. Filtrar los borrados ANTES de elegir la última versión "reviviría" registros
  eliminados; por eso el filtro va afuera.
#}
{% macro cdc_ultima_version(source_name, table_name) -%}
    select *
    from (
        select *
        from {{ source(source_name, table_name) }}
        qualify row_number() over (
            partition by {{ llave_fuente(source_name, table_name) | join(', ') }}
            order by {{ cdc_orden() }}
        ) = 1
    ) as ultima_version
    where _ab_cdc_deleted_at is null
{%- endmacro %}

{#
  Historia: todas las versiones distintas de cada llave (una fila por llave y LSN), incluidos
  los borrados. Se usa para construir dimensiones con vigencia (SCD2) desde el propio CDC.
#}
{% macro cdc_versiones(source_name, table_name) -%}
    select *
    from {{ source(source_name, table_name) }}
    qualify row_number() over (
        partition by {{ llave_fuente(source_name, table_name) | join(', ') }}, _ab_cdc_lsn
        order by _dp_ingerido_en desc
    ) = 1
{%- endmacro %}

{# Columnas de control tipadas que todo modelo de staging conserva. #}
{% macro cdc_columnas_control() -%}
    {{ dbt.safe_cast('_ab_cdc_lsn', dbt.type_numeric()) }} as _cdc_lsn,
    {{ dbt.safe_cast('_ab_cdc_updated_at', dbt.type_timestamp()) }} as _cdc_actualizado_en,
    {{ dbt.safe_cast('_airbyte_extracted_at', dbt.type_timestamp()) }} as _extraido_en,
    _dp_entrega
{%- endmacro %}
