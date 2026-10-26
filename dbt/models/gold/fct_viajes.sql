-- Hecho de viajes embarcados. Grano: un viaje.
-- El costo de flete vive solo aquí: es un monto por viaje (regla 4).
select
    id_viaje,
    cla_planta,
    fecha_embarque,
    {{ anio_mes('fecha_embarque') }} as anio_mes,
    costo_flete_mxn,
    tiene_pod,
    a_tiempo
from {{ ref('int_viajes__embarcados') }}
