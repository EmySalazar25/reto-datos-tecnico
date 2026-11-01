{#
  La fecha (sin hora) no puede ser anterior a la de referencia: p. ej. un viaje no se entrega
  antes de salir. Compara fechas, no horas, para no marcar entregas del mismo día; ambas
  columnas deben estar en la misma zona horaria.
#}
{% test fecha_no_anterior_a(model, column_name, columna_referencia) %}
select {{ column_name }}, {{ columna_referencia }}
from {{ model }}
where {{ column_name }} is not null
  and {{ columna_referencia }} is not null
  and cast({{ column_name }} as date) < cast({{ columna_referencia }} as date)
{% endtest %}
