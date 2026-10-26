-- R4: el costo de flete es por viaje. El costo publicado debe ser la suma del costo de cada
-- viaje embarcado contado UNA vez. Si el costo se suma a nivel partida, el total se infla
-- (en carga_1, unas 2 veces) y este test falla.
-- Tolerancia: redondeo a 2 decimales por fila publicada.
{{ config(tags=['business'], meta={'rule': 'R4'}) }}

with esperado as (
    select sum(costo_flete_mxn) as costo
    from {{ ref('stg_fle__viajes') }}
    where estatus in ('TRA', 'ENT')
),

publicado as (
    select
        sum(costo_flete_mxn) as costo,
        count(*) as filas
    from {{ ref('embarques_mensual') }}
)

select
    e.costo as esperado,
    p.costo as publicado,
    p.costo - e.costo as diferencia
from esperado as e
cross join publicado as p
where abs(p.costo - e.costo) > p.filas * 0.005 + 1e-9
