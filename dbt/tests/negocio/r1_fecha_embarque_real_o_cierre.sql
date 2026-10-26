-- R1: la fecha de embarque es la real; si no se capturó (nula o 1900-01-01), la de cierre.
-- Se recalcula desde staging. La tolerancia de 2 horas cubre la conversión a hora local de
-- planta (Houston); elegir la fecha equivocada desvía casi siempre mucho más.
{{ config(tags=['business'], meta={'rule': 'R1'}) }}

select
    f.id_viaje,
    f.fecha_embarque,
    s.fecha_real_embarque,
    s.fecha_embarque_final
from {{ ref('fct_viajes') }} as f
inner join {{ ref('stg_fle__viajes') }} as s on f.id_viaje = s.id_viaje
where f.fecha_embarque is null
   or abs({{ dbt.datediff('coalesce(s.fecha_real_embarque, s.fecha_embarque_final)', 'f.fecha_embarque', 'minute') }}) > 120
