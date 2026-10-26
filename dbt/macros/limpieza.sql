{#
  Limpieza de valores que llegan como texto desde SQL Server.
  Se usan en staging para que ningún modelo resuelva estas particularidades a mano.
  Los casts son "seguros" (nulo si no convierte); el test genérico `castea_a` sobre la
  fuente es el que hace visible cualquier valor que no convierta.
#}

{# Texto: sin espacios a los lados; vacío equivale a nulo. #}
{% macro texto(col) -%}
    nullif(trim({{ col }}), '')
{%- endmacro %}

{# Códigos de catálogo (estatus, segmento): mayúsculas y sin espacios. #}
{% macro codigo(col) -%}
    upper({{ texto(col) }})
{%- endmacro %}

{% macro entero(col) -%}
    {{ dbt.safe_cast(texto(col), dbt.type_int()) }}
{%- endmacro %}

{% macro numero(col, precision, scale) -%}
    {{ dbt.safe_cast(texto(col), 'decimal(' ~ precision ~ ',' ~ scale ~ ')') }}
{%- endmacro %}

{#
  Fecha de SQL Server. `1900-01-01` es el valor por defecto de un datetime que no se capturó:
  se trata como nulo para que la regla de negocio pueda usar el valor alterno.
#}
{% macro fecha_origen(col) -%}
    case
        when {{ dbt.safe_cast(texto(col), dbt.type_timestamp()) }} < {{ dbt.safe_cast("'1901-01-01'", dbt.type_timestamp()) }}
            then null
        else {{ dbt.safe_cast(texto(col), dbt.type_timestamp()) }}
    end
{%- endmacro %}

{#
  Convierte un timestamp UTC sin zona a hora local sin zona.
  Implementación por adaptador: DuckDB (probada) y BigQuery (diseño, no se ejecuta en el reto).
#}
{% macro utc_a_local(col, zona='America/Monterrey') -%}
    {{ return(adapter.dispatch('utc_a_local')(col, zona)) }}
{%- endmacro %}

{% macro default__utc_a_local(col, zona) -%}
    timezone('{{ zona }}', timezone('UTC', {{ col }}))
{%- endmacro %}

{% macro bigquery__utc_a_local(col, zona) -%}
    datetime(timestamp({{ col }}), '{{ zona }}')
{%- endmacro %}

{# Mes calendario en formato YYYY-MM. #}
{% macro anio_mes(col) -%}
    {{ return(adapter.dispatch('anio_mes')(col)) }}
{%- endmacro %}

{% macro default__anio_mes(col) -%}
    strftime({{ col }}, '%Y-%m')
{%- endmacro %}

{% macro bigquery__anio_mes(col) -%}
    format_date('%Y-%m', date({{ col }}))
{%- endmacro %}
