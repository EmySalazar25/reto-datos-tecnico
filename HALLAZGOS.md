# Hallazgos en los datos

Problemas de la réplica (`carga_1`) que nadie documentó. Las cifras salen del pipeline
implementado; cada una se puede reproducir con `dp profile <tabla>` o con los tests citados.

## Resumen de impacto en los indicadores

Qué tablero vería Logística si cada trampa no se atendiera:

| Error | Publicado con el error | Publicado correcto | Desviación |
|---|---|---|---|
| No deduplicar el CDC | 52,790.020 t | 49,773.464 t | +6.1 % de toneladas |
| Sumar el costo a nivel partida | $62,308,853.22 | $30,081,415.34 | 2.07 veces el costo |
| "A tiempo" con fecha y hora | 52.95 % | 70.37 % | −17.4 puntos |
| Segmento actual en vez del histórico | — | — | 3,639 t (7.3 %) de 12 clientes en el segmento equivocado |
| Inner join con el maestro de clientes | — | 991 t entregadas en `NO_IDENTIFICADO` | Esas toneladas desaparecen |

---

## H1. Cada cambio llega como una fila nueva, con duplicados exactos

- **Qué vimos.** `fle_viaje`: 5,850 filas para 1,905 viajes (hasta 5 versiones por viaje) y 126 filas duplicadas exactas. `fle_viaje_det`: 134 duplicados exactos. `vta_cliente`: 112 filas para 82 clientes.
- **Cómo se detectó.** `dp profile fle_viaje` (versiones por llave y duplicados exactos).
- **Impacto.** Sumar landing directo infla las toneladas 6.1 %.
- **Resolución.** Staging se queda con la última versión por llave (`cdc_ultima_version`). Tests: unicidad de la llave en staging y `combinacion_unica` en partidas; unit test `ut_cdc_…`; chaos CH-02.
- **Escalar.** Nada: es el comportamiento esperado de una réplica CDC. Sí documentar que los reenvíos existen.

## H2. El timestamp del cambio no ordena las versiones; solo el LSN

- **Qué vimos.** 44 viajes tienen dos versiones con el mismo `_ab_cdc_updated_at` y distinto `CostoFlete`: son correcciones de costo registradas en el mismo instante. Solo `_ab_cdc_lsn` dice cuál es la última.
- **Cómo se detectó.** `dp profile fle_viaje` ("llaves con empate de timestamp").
- **Impacto.** Ordenar por timestamp toma al azar el costo original o el corregido. Ningún test de datos lo nota, porque el error queda en staging y todo lo de abajo cuadra con él.
- **Resolución.** El orden es por LSN numérico, después timestamp, después la entrega más reciente. El unit test `ut_cdc_ultima_version_por_lsn_y_borrados` incluye un empate y un caso donde el timestamp contradice al LSN. El chaos CH-08 demuestra que **solo** el unit test lo atrapa.
- **Escalar.** Confirmar con el dueño del origen que el LSN es monótono también entre reinicios de la réplica.

## H3. Viajes borrados en el origen, con partidas que no se borraron

- **Qué vimos.** 24 viajes cuya última versión es un borrado, todos en tránsito (TRA), por $397,643.18 de flete. Sus 52 partidas siguen vivas en `fle_viaje_det`.
- **Cómo se detectó.** `dp profile fle_viaje` (llaves borradas) y la cobertura de partidas contra viajes.
- **Impacto.** Sin aplicar los borrados, se reportan viajes que no existen. Si los borrados se filtraran antes de elegir la última versión, reaparecerían versiones viejas de esos viajes.
- **Resolución.** El borrado se aplica después de elegir la última versión. Las partidas huérfanas quedan fuera por el join con sus viajes (supuesto S6). Tests: `excluye_borrados` en cada staging y `r2_partidas_solo_de_viajes_embarcados`.
- **Escalar.** El borrado de un viaje no se propaga a su detalle en el origen. ¿Es intencional?

## H4. Estatus escritos de 20 formas distintas

- **Qué vimos.** 20 variantes para 4 códigos (`Pro`, `tra`, `" ENT"`, `TRA ` …). 672 filas (11.5 %) no coinciden exactamente con `PRO/TRA/ENT/CAN`.
- **Cómo se detectó.** `dp profile fle_viaje` (espacios y variantes por mayúsculas).
- **Impacto.** Filtrar `estatus in ('TRA','ENT')` sin normalizar pierde viajes embarcados sin avisar.
- **Resolución.** Macro `codigo()` (`upper(trim())`) y `accepted_values` sobre el valor normalizado. Si el origen manda un valor nuevo (`'En Transito'`), el test falla y el producto queda `DEGRADED` (chaos CH-09) en vez de perder viajes en silencio.
- **Escalar.** Restringir el campo a un catálogo en el sistema origen.

## H5. Fecha centinela `1900-01-01`

- **Qué vimos.** 1,369 filas con `FechaRealEmbarque = 1900-01-01` (el valor por defecto de un `datetime` de SQL Server sin capturar) y 2,008 nulas.
- **Cómo se detectó.** `dp profile fle_viaje` (`fecha_centinela_1900`).
- **Impacto.** Un `coalesce` ingenuo toma 1900 como fecha real: esos embarques caen en enero de 1900 y desaparecen de los meses de 2026.
- **Resolución.** La macro `fecha_origen()` convierte el centinela a nulo y la regla R1 toma la fecha de cierre. Test `sin_fecha_centinela`; chaos CH-10 para la regla.
- **Escalar.** Que el origen guarde nulo en lugar del valor por defecto.

## H6. Cierres de documento en lote a las 08:00 del día siguiente

- **Qué vimos.** 251 viajes con `FechaEmbarqueFinal` exactamente a las 08:00 del día siguiente a la salida real.
- **Cómo se detectó.** Perfil de horas de `FechaEmbarqueFinal`.
- **Impacto.** 618 viajes embarcados no tienen fecha real y usan la de cierre. Entre los viajes que sí tienen ambas, 10 cierres en lote caen en el mes siguiente a la salida real: es la magnitud del riesgo de que algunos de esos 618 estén reportados en el mes equivocado.
- **Resolución.** Se aplica la regla acordada (R1); el riesgo queda documentado y medido.
- **Escalar.** Confirmar si el cierre en lote es un proceso nocturno; si es así, la fecha de cierre no debería usarse como sustituto de la salida.

## H7. Comprobantes de entrega (POD) corregidos

- **Qué vimos.** 88 viajes con su POD corregido: 46 se movieron a una fecha posterior y 42 a una anterior. En 15 viajes la corrección cambia el resultado de "a tiempo".
- **Cómo se detectó.** Versiones de `fle_entrega` por viaje.
- **Impacto.** Usar la primera captura en lugar de la última cambia el indicador de 15 viajes.
- **Resolución.** Se usa la última versión por LSN (H2).
- **Escalar.** Pedir el motivo de las correcciones: si son errores de captura, el proceso de Tráfico necesita un control.

## H8. "A tiempo": la fecha compromiso viene a medianoche

- **Qué vimos.** `FechaCompromiso` siempre a las 00:00; `FechaEntrega` con hora.
- **Cómo se detectó.** Perfil de horas de ambas columnas.
- **Impacto.** Comparar fecha y hora marca como tarde casi toda entrega del día compromiso: 52.95 % contra 70.37 %.
- **Resolución.** Se comparan fechas (supuesto S1). Unit test con un POD a las 18:00 del día compromiso; chaos CH-05.
- **Escalar.** Confirmar con Logística que el compromiso es "durante el día" y no una hora.

## H9. El segmento del cliente cambia en el tiempo

- **Qué vimos.** 12 clientes cambiaron de segmento entre enero y junio. Hay versiones que solo cambian el nombre a mayúsculas y segmentos con espacios o en minúsculas (`'Industrial '`).
- **Cómo se detectó.** `dp profile vta_cliente` y la historia de versiones.
- **Impacto.** Usar el segmento actual mueve 3,639 t (7.3 %) al segmento equivocado.
- **Resolución.** Vigencia (SCD2) construida desde las versiones CDC, desde el día local del cambio, ignorando cambios que no son de segmento. No se usa `dbt snapshot`, que registraría la fecha de nuestra corrida y no la del cambio. Tests: `vigencias_continuas`, `r6_…` (con un método independiente) y dos unit tests; chaos CH-04.
- **Escalar.** Nada.

## H10. Clientes que no existen en el maestro

- **Qué vimos.** Partidas de los clientes 9001, 9002 y 9003, que no están en `vta_cliente`: 67 partidas embarcadas, 991 t entregadas. Además, dos clientes "PRUEBA NO USAR" borrados del maestro, sin embarques.
- **Cómo se detectó.** Cobertura del join partidas → clientes (`cobertura_minima`: 98.18 % de las partidas encuentran cliente).
- **Impacto.** Un inner join pierde esas toneladas sin error.
- **Resolución.** Se reportan como `NO_IDENTIFICADO` (regla R7) y la cobertura se mide con un umbral de advertencia. Chaos CH-03.
- **Escalar.** Dar de alta esos clientes o explicar de dónde vienen las claves 900x.

## H11. Estatus y POD que no concuerdan

- **Qué vimos.** 29 viajes entregados (ENT) sin POD y 1 viaje en tránsito (TRA) con POD.
- **Cómo se detectó.** Cruce de `int_viajes__embarcados` contra entregas.
- **Impacto.** Los 29 no se pueden evaluar como a tiempo; el indicador es sobre las toneladas con POD.
- **Resolución.** Se aplica la regla: solo se evalúan viajes con POD (supuesto S7).
- **Escalar.** El POD se captura cuando llega el documento físico; 29 viajes entregados sin POD sugieren un rezago de captura en Tráfico.

## H12. Partidas idénticas dentro del mismo viaje

- **Qué vimos.** 93 combinaciones de viaje, cliente, artículo y peso que aparecen en más de una partida.
- **Cómo se detectó.** Agrupación de `stg_fle__partidas`.
- **Impacto.** Si son capturas duplicadas, las toneladas están infladas; si son legítimas, todo está bien.
- **Resolución.** Se conservan: tienen `IdPartida` distinto y no hay evidencia de que sean duplicadas.
- **Escalar.** Confirmar con el origen si una partida puede repetirse con el mismo peso.

## H13. Zona horaria de la planta de Houston

- **Qué vimos.** El diccionario dice que todas las fechas están en hora de Monterrey, pero la regla pide "hora local de planta" y Houston usa horario de verano.
- **Cómo se detectó.** Lectura del diccionario contra la regla R1.
- **Impacto.** Embarques de Houston cerca de la medianoche del último día del mes cambiarían de mes. Hoy no hay ninguno.
- **Resolución.** La fecha se convierte a la zona de la planta (supuesto S2). Unit test con un embarque a las 23:30 del 31 de julio que en Houston ya es 1 de agosto.
- **Escalar.** Confirmar en qué zona captura el sistema origen las fechas de Houston.
