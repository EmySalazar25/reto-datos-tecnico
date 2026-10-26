-- Catálogo de plantas: estado actual (última versión CDC, sin borrados).
with ultima as (
    {{ cdc_ultima_version('landing_opc', 'opc_planta') }}
)

select
    {{ entero('ClaPlanta') }}  as cla_planta,
    {{ texto('NomPlanta') }}   as nom_planta,
    {{ codigo('ClaPais') }}    as cla_pais,
    {{ cdc_columnas_control() }}
from ultima
