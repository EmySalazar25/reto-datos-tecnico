-- R2: solo cuentan los viajes en estatus TRA o ENT. El total publicado de viajes debe ser
-- exactamente el número de viajes vigentes con esos estatus en staging.
{{ config(tags=['business'], meta={'rule': 'R2'}) }}

with esperado as (
    select count(*) as viajes
    from {{ ref('stg_fle__viajes') }}
    where estatus in ('TRA', 'ENT')
),

publicado as (
    select sum(num_viajes) as viajes
    from {{ ref('embarques_mensual') }}
)

select
    e.viajes as esperado,
    p.viajes as publicado
from esperado as e
cross join publicado as p
where e.viajes <> p.viajes
