{#
  CDC: falla con cada llave cuyo último cambio en la réplica es un borrado y que aun así
  aparece en el modelo (un registro eliminado en el origen "revivido").
#}
{% test excluye_borrados(model, source_name, table_name, llave_modelo) %}
{%- set pk = llave_fuente(source_name, table_name) -%}
with ultima as (
    select *
    from {{ source(source_name, table_name) }}
    qualify row_number() over (
        partition by {{ pk | join(', ') }}
        order by {{ cdc_orden() }}
    ) = 1
),

borrados as (
    select
        {%- for c in pk %}
        trim({{ c }}) as llave_{{ loop.index }}{{ ',' if not loop.last }}
        {%- endfor %}
    from ultima
    where _ab_cdc_deleted_at is not null
)

select m.*
from {{ model }} as m
inner join borrados as b
    on {% for c in llave_modelo -%}
    cast(m.{{ c }} as {{ dbt.type_string() }}) = b.llave_{{ loop.index }}{{ ' and ' if not loop.last }}
    {%- endfor %}
{% endtest %}
