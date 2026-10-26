{#
  Fechas inválidas: falla con cada valor anterior a 1901. En SQL Server `1900-01-01` es el
  valor por defecto de un datetime que nadie capturó; nunca debe llegar a un modelo.
#}
{% test sin_fecha_centinela(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} < {{ dbt.safe_cast("'1901-01-01'", dbt.type_timestamp()) }}
{% endtest %}
