{#
  Fan-out: falla si el total de una medida en el modelo no coincide con el total en el grano
  donde la medida vive (p. ej. el costo por viaje). Un join que multiplica filas infla el total
  sin marcar ningún error; este test lo hace visible.

  La tolerancia sale del redondeo del propio modelo: cada fila redondeada a `decimales` puede
  desviarse a lo más media unidad de la última cifra.
#}
{% test no_fanout(model, column_name, referencia, columna_referencia, decimales=2, condicion_referencia=none) %}
with modelo as (
    select
        sum({{ column_name }}) as total,
        count(*) as filas
    from {{ model }}
),

referencia as (
    select sum({{ columna_referencia }}) as total
    from {{ referencia }}
    {% if condicion_referencia %}where {{ condicion_referencia }}{% endif %}
)

select
    m.total as total_modelo,
    r.total as total_referencia,
    m.total - r.total as diferencia
from modelo as m
cross join referencia as r
where abs(coalesce(m.total, 0) - coalesce(r.total, 0)) > m.filas * 0.5 * power(10, -{{ decimales }}) + 1e-9
{% endtest %}
