-- R1 en el linaje de partidas: cada partida hereda la fecha de embarque de su viaje (real o,
-- si no se capturó, de cierre). Protege a los productos que agregan desde fct_embarques.
{{ config(tags=['business'], meta={'rule': 'R1'}) }}

select
    f.id_viaje,
    f.id_partida,
    f.fecha_embarque,
    s.fecha_real_embarque,
    s.fecha_embarque_final
from {{ ref('fct_embarques') }} as f
inner join {{ ref('stg_fle__viajes') }} as s on f.id_viaje = s.id_viaje
where f.fecha_embarque is null
   or abs({{ dbt.datediff('coalesce(s.fecha_real_embarque, s.fecha_embarque_final)', 'f.fecha_embarque', 'minute') }}) > 120
