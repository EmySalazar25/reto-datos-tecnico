-- Segmento de cada cliente con su periodo de vigencia (SCD2), construido desde la historia CDC.
-- Regla 6: el cambio aplica desde el día (hora local) en que se registra en el origen.
-- No se usa `dbt snapshot`: registraría la fecha de nuestra corrida, no la fecha del cambio.
with versiones as (
    select
        cla_cliente,
        segmento,
        _cdc_lsn,
        _cdc_borrado_en,
        cast({{ utc_a_local('_cdc_actualizado_en', var('zona_horaria_origen')) }} as date) as dia_cambio
    from {{ ref('stg_vta__clientes_versiones') }}
),

-- Si hay varias versiones el mismo día, vale la última del día.
ultima_del_dia as (
    select *
    from versiones
    qualify row_number() over (partition by cla_cliente, dia_cambio order by _cdc_lsn desc) = 1
),

con_anterior as (
    select
        *,
        lag(segmento) over (partition by cla_cliente order by _cdc_lsn) as segmento_anterior,
        lag(_cdc_borrado_en) over (partition by cla_cliente order by _cdc_lsn) as borrado_anterior,
        row_number() over (partition by cla_cliente order by _cdc_lsn) as orden
    from ultima_del_dia
),

-- Solo abren vigencia nueva los cambios de segmento y los borrados. Una versión que solo
-- corrige el nombre no parte la historia.
cambios as (
    select *
    from con_anterior
    where orden = 1
       or _cdc_borrado_en is not null
       or borrado_anterior is not null
       or segmento is distinct from segmento_anterior
),

vigencias as (
    select
        cla_cliente,
        segmento,
        _cdc_borrado_en,
        -- Supuesto S3: la primera versión CDC es la foto inicial; vale desde siempre (nulo).
        case when orden = 1 then null else dia_cambio end as vigente_desde,
        lead(dia_cambio) over (partition by cla_cliente order by _cdc_lsn) as vigente_hasta
    from cambios
)

-- Una versión de borrado cierra la vigencia anterior y no es un segmento en sí.
select
    cla_cliente,
    segmento,
    vigente_desde,
    vigente_hasta,
    vigente_hasta is null as es_vigente
from vigencias
where _cdc_borrado_en is null
