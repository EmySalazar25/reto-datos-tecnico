{#
  Casts sin pérdida silenciosa: falla con cada valor no vacío de la fuente que no convierte al
  tipo esperado. Staging usa casts seguros (nulo si no convierte); este test hace visible lo que
  un cast seguro escondería, con el valor exacto como evidencia.
#}
{% test castea_a(model, column_name, tipo) %}
select
    {{ column_name }} as valor,
    count(*) as filas
from {{ model }}
where nullif(trim({{ column_name }}), '') is not null
  and {{ dbt.safe_cast('trim(' ~ column_name ~ ')', tipo) }} is null
group by 1
{% endtest %}
