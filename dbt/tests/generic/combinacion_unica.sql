{#
  Grano / llave compuesta: falla con cada combinación de columnas que aparece más de una vez.
  Es el test que protege el grano declarado en `meta.grain`.
#}
{% test combinacion_unica(model, columnas) %}
select
    {{ columnas | join(', ') }},
    count(*) as repeticiones
from {{ model }}
group by {{ columnas | join(', ') }}
having count(*) > 1
{% endtest %}
