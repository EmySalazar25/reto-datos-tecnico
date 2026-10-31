{#
  Una fecha no puede ser posterior a la de referencia: p. ej. nada pudo ocurrir después de que
  se extrajo el propio registro. Si la referencia viene en UTC y la columna en hora local,
  `zona_referencia` convierte la referencia a esa zona antes de comparar. Es determinista: no
  usa la hora actual, así que respeta el reloj replay.
#}
{% test fecha_no_posterior_a(model, column_name, columna_referencia, zona_referencia=none) %}
{%- set referencia = utc_a_local(columna_referencia, zona_referencia) if zona_referencia else columna_referencia %}
select {{ column_name }}, {{ referencia }} as referencia
from {{ model }}
where {{ column_name }} is not null
  and {{ columna_referencia }} is not null
  and {{ column_name }} > {{ referencia }}
{% endtest %}
