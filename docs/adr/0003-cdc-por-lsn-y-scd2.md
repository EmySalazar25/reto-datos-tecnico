# ADR 0003. Deduplicación CDC por LSN y vigencias construidas desde la historia CDC

**Estado:** aceptada

## Contexto

Airbyte CDC entrega cada cambio como una fila nueva, con duplicados exactos y borrados como una
versión más. En `carga_1`, 44 viajes tienen correcciones de costo con el mismo
`_ab_cdc_updated_at` que la versión original. Además, la regla 6 exige el segmento del cliente
vigente el día del embarque, no el actual.

## Alternativas

**Orden de versiones:** por `_ab_cdc_updated_at`, por orden de llegada o por `_ab_cdc_lsn`.

**Historia del segmento:** `dbt snapshot` sobre el maestro, o vigencias construidas desde las
versiones CDC que ya trae la réplica.

## Decisión

- Una sola macro, `cdc_ultima_version`, para todo staging: la última versión por llave ordenada por
  **LSN numérico**, después timestamp, después la entrega más reciente. El borrado se aplica
  **después** de elegir la última versión, para no revivir versiones previas de un registro
  eliminado. La llave se lee de `meta.primary_key` de la fuente; no se repite en cada modelo.
- La vigencia del segmento (SCD2) se construye desde `cdc_versiones`: cada cambio vale desde el
  día local en que se registró en el origen. No se usa `dbt snapshot`, que registraría la fecha de
  nuestra corrida y fecharía mal cualquier cambio anterior a la primera ejecución.

## Consecuencias

- Correr dos veces o recibir reenvíos no duplica nada: la idempotencia sale del diseño, no de
  una limpieza posterior.
- La historia es reconstruible desde landing en cualquier momento.
- El orden por LSN solo lo protege un unit test con un caso controlado: los tests de datos no lo
  ven porque todo lo de abajo cuadra con el mismo staging (chaos CH-08).
- Si el LSN no fuera monótono entre reinicios de la réplica, habría que revisar el desempate:
  queda escalado al dueño del origen.
