-- R5: una partida llega a tiempo si la FECHA del POD es menor o igual a la fecha compromiso.
-- La fecha compromiso viene a medianoche: comparar fecha y hora marcaría como tarde casi toda
-- entrega del mismo día. Se recalculan las toneladas a tiempo desde staging.
-- Tolerancia: redondeo a 3 decimales por fila publicada.
{{ config(tags=['business'], meta={'rule': 'R5'}) }}

with esperado as (
    select
        sum(p.peso_kg) / 1000 as entregadas,
        sum(case when cast(e.fecha_entrega as date) <= cast(v.fecha_compromiso as date) then p.peso_kg end) / 1000 as a_tiempo
    from {{ ref('stg_fle__partidas') }} as p
    inner join {{ ref('stg_fle__viajes') }} as v on p.id_viaje = v.id_viaje
    inner join {{ ref('stg_fle__entregas') }} as e on p.id_viaje = e.id_viaje
    where v.estatus in ('TRA', 'ENT')
),

publicado as (
    select
        sum(toneladas_entregadas) as entregadas,
        sum(toneladas_a_tiempo) as a_tiempo,
        count(*) as filas
    from {{ ref('cumplimiento_entrega') }}
)

select
    e.entregadas as esperado_entregadas,
    p.entregadas as publicado_entregadas,
    e.a_tiempo as esperado_a_tiempo,
    p.a_tiempo as publicado_a_tiempo
from esperado as e
cross join publicado as p
where abs(p.entregadas - e.entregadas) > p.filas * 0.0005 + 1e-9
   or abs(p.a_tiempo - e.a_tiempo) > p.filas * 0.0005 + 1e-9
