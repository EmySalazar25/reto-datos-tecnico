{#
  Valor posible: falla con cada valor fuera de [minimo, maximo]. Con `minimo_exclusivo`, el
  mínimo mismo tampoco vale (p. ej. un peso de 0 kg). Los nulos los revisa `not_null` aparte.
  Un límite que no es un invariante físico es un umbral de negocio: va como var con su
  justificación, no fijo en el YAML.
#}
{% test rango(model, column_name, minimo=none, maximo=none, minimo_exclusivo=false) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and (
      false
      {%- if minimo is not none %}
      or {{ column_name }} {{ '<=' if minimo_exclusivo else '<' }} {{ minimo }}
      {%- endif %}
      {%- if maximo is not none %}
      or {{ column_name }} > {{ maximo }}
      {%- endif %}
  )
{% endtest %}
