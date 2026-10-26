{#
  SCD2: falla si los periodos de vigencia de una llave se traslapan o dejan huecos, o si hay más
  de un periodo abierto al inicio o al final. Con esto, cada fecha cae en a lo más un periodo.
#}
{% test vigencias_continuas(model, llave, desde, hasta) %}
with ordenado as (
    select
        {{ llave }} as llave,
        {{ desde }} as desde,
        {{ hasta }} as hasta,
        lead({{ desde }}) over (partition by {{ llave }} order by {{ desde }} nulls first) as siguiente_desde,
        count(*) filter (where {{ desde }} is null) over (partition by {{ llave }}) as abiertos_inicio,
        count(*) filter (where {{ hasta }} is null) over (partition by {{ llave }}) as abiertos_fin
    from {{ model }}
)

select *
from ordenado
where (siguiente_desde is not null and hasta is distinct from siguiente_desde)
   or abiertos_inicio > 1
   or abiertos_fin > 1
   or (desde is not null and hasta is not null and hasta <= desde)
{% endtest %}
