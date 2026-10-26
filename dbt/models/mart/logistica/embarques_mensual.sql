-- Producto publicado: toneladas, viajes y costo de flete por planta y mes.
-- Viajes y costo se agregan desde el grano viaje; toneladas desde el grano partida. Se unen
-- ya agregados por (anio_mes, cla_planta), así ningún monto se repite.
with viajes as (
    select
        anio_mes,
        cla_planta,
        count(*) as num_viajes,
        sum(costo_flete_mxn) as costo_flete_mxn
    from {{ ref('fct_viajes') }}
    group by anio_mes, cla_planta
),

toneladas as (
    select
        anio_mes,
        cla_planta,
        sum(toneladas) as toneladas
    from {{ ref('fct_embarques') }}
    group by anio_mes, cla_planta
),

redondeado as (
    select
        v.anio_mes,
        v.cla_planta,
        pl.nom_planta,
        v.num_viajes,
        round(coalesce(t.toneladas, 0), 3) as toneladas_embarcadas,
        round(v.costo_flete_mxn, 2) as costo_flete_mxn
    from viajes as v
    left join toneladas as t on v.anio_mes = t.anio_mes and v.cla_planta = t.cla_planta
    left join {{ ref('dim_planta') }} as pl on v.cla_planta = pl.cla_planta
)

-- costo_flete_por_ton se calcula con las columnas publicadas para que BI pueda reproducirlo.
select
    cast(anio_mes as varchar) as anio_mes,
    cast(cla_planta as integer) as cla_planta,
    cast(nom_planta as varchar) as nom_planta,
    cast(num_viajes as integer) as num_viajes,
    cast(toneladas_embarcadas as decimal(18, 3)) as toneladas_embarcadas,
    cast(costo_flete_mxn as decimal(18, 2)) as costo_flete_mxn,
    cast(round(costo_flete_mxn / nullif(toneladas_embarcadas, 0), 2) as decimal(18, 2)) as costo_flete_por_ton
from redondeado
