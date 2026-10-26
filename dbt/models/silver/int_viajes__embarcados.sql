-- Viajes que cuentan como embarcados y su puntualidad.
--   Regla 1: fecha de embarque = real; si no se capturó, la de cierre. En hora local de planta.
--   Regla 2: solo estatus TRA y ENT.
--   Regla 5: a tiempo si la fecha (no la hora) de entrega del POD <= fecha compromiso.
--            Solo se evalúan viajes con POD.
with viajes as (
    select *
    from {{ ref('stg_fle__viajes') }}
    where estatus in ({{ "'" ~ var('estatus_embarcado') | join("', '") ~ "'" }})
),

plantas as (
    select
        cla_planta,
        case cla_pais
            {%- for pais, zona in var('zona_horaria_por_pais').items() %}
            when '{{ pais }}' then '{{ zona }}'
            {%- endfor %}
        end as zona_horaria
    from {{ ref('stg_opc__plantas') }}
)

select
    v.id_viaje,
    v.cla_planta,
    v.estatus,
    case when v.fecha_real_embarque is not null then 'REAL' else 'CIERRE' end as origen_fecha_embarque,
    {{ local_a_local(
        'coalesce(v.fecha_real_embarque, v.fecha_embarque_final)',
        var('zona_horaria_origen'),
        'p.zona_horaria'
    ) }} as fecha_embarque,
    v.fecha_compromiso,
    v.costo_flete_mxn,
    e.fecha_entrega,
    e.id_viaje is not null as tiene_pod,
    case
        when e.id_viaje is null then null
        else cast(e.fecha_entrega as date) <= cast(v.fecha_compromiso as date)
    end as a_tiempo
from viajes as v
inner join plantas as p on v.cla_planta = p.cla_planta
left join {{ ref('stg_fle__entregas') }} as e on v.id_viaje = e.id_viaje
