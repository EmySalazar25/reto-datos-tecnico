-- R6: el segmento de cada partida es el que tenía el cliente el día del embarque.
-- Se recalcula con un método distinto al del modelo: la última versión CDC registrada (día
-- local) hasta la fecha de embarque; si no hay ninguna, la primera versión (foto inicial).
{{ config(tags=['business'], meta={'rule': 'R6'}) }}

with versiones as (
    select
        cla_cliente,
        segmento,
        _cdc_lsn,
        _cdc_borrado_en,
        cast({{ utc_a_local('_cdc_actualizado_en', var('zona_horaria_origen')) }} as date) as dia_cambio
    from {{ ref('stg_vta__clientes_versiones') }}
),

esperado as (
    select
        f.id_viaje,
        f.id_partida,
        f.segmento_cliente,
        (
            select case when v._cdc_borrado_en is null then v.segmento end
            from versiones as v
            where v.cla_cliente = f.cla_cliente
              and v.dia_cambio <= cast(f.fecha_embarque as date)
            order by v._cdc_lsn desc
            limit 1
        ) as segmento_a_la_fecha,
        (
            select v.segmento
            from versiones as v
            where v.cla_cliente = f.cla_cliente
            order by v._cdc_lsn
            limit 1
        ) as segmento_inicial,
        exists (
            select 1
            from versiones as v
            where v.cla_cliente = f.cla_cliente
              and v.dia_cambio <= cast(f.fecha_embarque as date)
        ) as hay_version_a_la_fecha
    from {{ ref('fct_embarques') }} as f
)

select *
from esperado
where segmento_cliente <> coalesce(
    case when hay_version_a_la_fecha then segmento_a_la_fecha else segmento_inicial end,
    'NO_IDENTIFICADO'
)
