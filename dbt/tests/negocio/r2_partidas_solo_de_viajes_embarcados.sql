-- R2 en el linaje de partidas: ninguna partida publicada pertenece a un viaje programado,
-- cancelado o borrado; y no falta ninguna partida de un viaje embarcado.
{{ config(tags=['business'], meta={'rule': 'R2'}) }}

with esperado as (
    select p.id_viaje, p.id_partida
    from {{ ref('stg_fle__partidas') }} as p
    inner join {{ ref('stg_fle__viajes') }} as v on p.id_viaje = v.id_viaje
    where v.estatus in ('TRA', 'ENT')
),

publicado as (
    select id_viaje, id_partida
    from {{ ref('fct_embarques') }}
)

select 'sobra' as diferencia, *
from (select * from publicado except select * from esperado)
union all
select 'falta' as diferencia, *
from (select * from esperado except select * from publicado)
