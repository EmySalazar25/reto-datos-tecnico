-- Partidas del viaje: estado actual (última versión CDC, sin borrados).
with ultima as (
    {{ cdc_ultima_version('landing_fle', 'fle_viaje_det') }}
)

select
    {{ entero('IdViaje') }}        as id_viaje,
    {{ entero('IdPartida') }}      as id_partida,
    {{ entero('ClaCliente') }}     as cla_cliente,
    {{ entero('ClaArticulo') }}    as cla_articulo,
    {{ numero('PesoKg', 18, 3) }}  as peso_kg,
    {{ cdc_columnas_control() }}
from ultima
