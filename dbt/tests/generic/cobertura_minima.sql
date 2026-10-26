{#
  Cobertura de un join: falla si el % de filas que SÍ encontraron pareja queda por debajo del
  mínimo. Las filas sin pareja no desaparecen (se marcan con `valor_desconocido`); este test
  mide cuántas son, para que un maestro incompleto no pase inadvertido.
#}
{% test cobertura_minima(model, column_name, valor_desconocido, minimo_pct) %}
with medicion as (
    select
        count(*) as filas,
        count(*) filter (where {{ column_name }} = '{{ valor_desconocido }}') as sin_pareja
    from {{ model }}
)

select
    filas,
    sin_pareja,
    round(100.0 * (filas - sin_pareja) / nullif(filas, 0), 2) as cobertura_pct,
    {{ minimo_pct }} as minimo_pct
from medicion
where 100.0 * (filas - sin_pareja) / nullif(filas, 0) < {{ minimo_pct }}
{% endtest %}
