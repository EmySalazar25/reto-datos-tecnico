-- Dimensión de plantas.
select
    cla_planta,
    nom_planta,
    cla_pais
from {{ ref('stg_opc__plantas') }}
