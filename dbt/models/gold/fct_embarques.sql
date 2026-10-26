-- Hecho de partidas embarcadas. Grano: un viaje y partida.
--   Regla 3: toneladas por peso documentado (kg / 1,000).
--   Regla 5: cada partida hereda la puntualidad de su viaje.
--   Regla 6: segmento vigente el día del embarque.
--   Regla 7: cliente sin segmento vigente en el maestro = NO_IDENTIFICADO (no se pierde).
-- No lleva costo: unirlo aquí lo repetiría por partida.
with partidas as (
    select
        p.id_viaje,
        p.id_partida,
        p.cla_cliente,
        p.peso_kg,
        v.cla_planta,
        v.fecha_embarque,
        v.tiene_pod,
        v.a_tiempo
    from {{ ref('stg_fle__partidas') }} as p
    inner join {{ ref('int_viajes__embarcados') }} as v on p.id_viaje = v.id_viaje
)

select
    p.id_viaje,
    p.id_partida,
    p.cla_planta,
    p.fecha_embarque,
    {{ anio_mes('p.fecha_embarque') }} as anio_mes,
    p.cla_cliente,
    s.cla_cliente is not null as cliente_identificado,
    coalesce(s.segmento, 'NO_IDENTIFICADO') as segmento_cliente,
    p.peso_kg,
    p.peso_kg / 1000 as toneladas,
    p.tiene_pod,
    p.a_tiempo
from partidas as p
left join {{ ref('int_clientes__vigencia_segmento') }} as s
    on p.cla_cliente = s.cla_cliente
    and (s.vigente_desde is null or s.vigente_desde <= cast(p.fecha_embarque as date))
    and (s.vigente_hasta is null or cast(p.fecha_embarque as date) < s.vigente_hasta)
