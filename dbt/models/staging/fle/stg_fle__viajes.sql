-- Viajes: estado actual (última versión CDC, sin borrados). Limpieza 1:1, sin reglas de negocio.
with ultima as (
    {{ cdc_ultima_version('landing_fle', 'fle_viaje') }}
)

select
    {{ entero('IdViaje') }}                  as id_viaje,
    {{ entero('ClaPlanta') }}                as cla_planta,
    {{ fecha_origen('FechaCompromiso') }}    as fecha_compromiso,
    {{ fecha_origen('FechaRealEmbarque') }}  as fecha_real_embarque,
    {{ fecha_origen('FechaEmbarqueFinal') }} as fecha_embarque_final,
    {{ codigo('Estatus') }}                  as estatus,
    {{ numero('CostoFlete', 18, 2) }}        as costo_flete_mxn,
    {{ cdc_columnas_control() }}
from ultima
