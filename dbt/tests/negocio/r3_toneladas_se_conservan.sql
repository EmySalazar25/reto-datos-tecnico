-- R3: las toneladas publicadas son exactamente el peso documentado de las partidas de viajes
-- embarcados (kg / 1,000). Un join que multiplica o pierde partidas rompe esta igualdad.
-- Tolerancia: redondeo a 3 decimales por fila publicada.
{{ config(tags=['business'], meta={'rule': 'R3'}) }}

with esperado as (
    select sum(p.peso_kg) / 1000 as toneladas
    from {{ ref('stg_fle__partidas') }} as p
    inner join {{ ref('stg_fle__viajes') }} as v on p.id_viaje = v.id_viaje
    where v.estatus in ('TRA', 'ENT')
),

publicado as (
    select
        sum(toneladas_embarcadas) as toneladas,
        count(*) as filas
    from {{ ref('embarques_mensual') }}
)

select
    e.toneladas as esperado,
    p.toneladas as publicado,
    p.toneladas - e.toneladas as diferencia
from esperado as e
cross join publicado as p
where abs(p.toneladas - e.toneladas) > p.filas * 0.0005 + 1e-9
