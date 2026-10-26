-- Historia del maestro de clientes: una fila por versión CDC distinta, incluidos los borrados.
-- Insumo para la dimensión con vigencia (el segmento cambia en el tiempo).
with versiones as (
    {{ cdc_versiones('landing_vta', 'vta_cliente') }}
)

select
    {{ entero('ClaCliente') }}  as cla_cliente,
    {{ texto('NomCliente') }}   as nom_cliente,
    {{ codigo('Segmento') }}    as segmento,
    {{ texto('ClaEstado') }}    as cla_estado,
    {{ dbt.safe_cast('_ab_cdc_deleted_at', dbt.type_timestamp()) }} as _cdc_borrado_en,
    {{ cdc_columnas_control() }}
from versiones
