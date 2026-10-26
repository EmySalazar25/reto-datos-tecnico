-- Comprobantes de entrega (POD): estado actual (última versión CDC, sin borrados).
with ultima as (
    {{ cdc_ultima_version('landing_fle', 'fle_entrega') }}
)

select
    {{ entero('IdViaje') }}             as id_viaje,
    {{ fecha_origen('FechaEntrega') }}  as fecha_entrega,
    {{ cdc_columnas_control() }}
from ultima
