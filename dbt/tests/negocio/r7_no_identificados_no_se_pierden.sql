-- R7: las partidas con cliente que no existe en el maestro no se pierden: sus toneladas se
-- reportan en NO_IDENTIFICADO. Se comparan las toneladas entregadas de esos clientes,
-- calculadas desde staging, con lo publicado en ese segmento.
{{ config(tags=['business'], meta={'rule': 'R7'}) }}

with esperado as (
    select coalesce(sum(p.peso_kg), 0) / 1000 as toneladas
    from {{ ref('stg_fle__partidas') }} as p
    inner join {{ ref('stg_fle__viajes') }} as v on p.id_viaje = v.id_viaje
    inner join {{ ref('stg_fle__entregas') }} as e on p.id_viaje = e.id_viaje
    where v.estatus in ('TRA', 'ENT')
      and not exists (
          select 1
          from {{ ref('stg_vta__clientes_versiones') }} as c
          where c.cla_cliente = p.cla_cliente
      )
),

publicado as (
    select
        coalesce(sum(toneladas_entregadas), 0) as toneladas,
        count(*) as filas
    from {{ ref('cumplimiento_entrega') }}
    where segmento_cliente = 'NO_IDENTIFICADO'
)

select
    e.toneladas as esperado,
    p.toneladas as publicado
from esperado as e
cross join publicado as p
where abs(p.toneladas - e.toneladas) > greatest(p.filas, 1) * 0.0005 + 1e-9
