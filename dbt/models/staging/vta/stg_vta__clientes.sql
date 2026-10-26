-- Maestro de clientes: estado actual (última versión CDC, sin borrados).
with ultima as (
    {{ cdc_ultima_version('landing_vta', 'vta_cliente') }}
)

select
    {{ entero('ClaCliente') }}  as cla_cliente,
    {{ texto('NomCliente') }}   as nom_cliente,
    {{ codigo('Segmento') }}    as segmento,
    {{ texto('ClaEstado') }}    as cla_estado,
    {{ cdc_columnas_control() }}
from ultima
