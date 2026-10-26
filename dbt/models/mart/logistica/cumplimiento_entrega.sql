-- Producto publicado: % de toneladas entregadas a tiempo por segmento de cliente y mes.
-- Solo partidas cuyo viaje ya tiene POD (regla 5); segmento vigente el día del embarque (regla 6).
with por_segmento as (
    select
        anio_mes,
        segmento_cliente,
        round(sum(toneladas), 3) as toneladas_entregadas,
        round(coalesce(sum(case when a_tiempo then toneladas end), 0), 3) as toneladas_a_tiempo
    from {{ ref('fct_embarques') }}
    where tiene_pod
    group by anio_mes, segmento_cliente
)

select
    cast(anio_mes as varchar) as anio_mes,
    cast(segmento_cliente as varchar) as segmento_cliente,
    cast(toneladas_entregadas as decimal(18, 3)) as toneladas_entregadas,
    cast(toneladas_a_tiempo as decimal(18, 3)) as toneladas_a_tiempo,
    cast(round(100 * toneladas_a_tiempo / nullif(toneladas_entregadas, 0), 2) as decimal(18, 2)) as pct_a_tiempo
from por_segmento
