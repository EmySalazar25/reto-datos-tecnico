# Propuesta: adoptar el estándar en un equipo de 6 personas

## El problema que resuelve

Replicamos decenas de sistemas y, después de la réplica, cada persona modela, prueba y entrega
a su manera. El resultado son marts que cuadran "más o menos" y que nadie certifica. En el caso
de Logística, las trampas de la réplica producen un tablero que **se ve bien y está mal**: +6 %
de toneladas por no deduplicar el CDC, el costo de flete al doble por un join y 17 puntos menos
de puntualidad por comparar horas en lugar de fechas ([HALLAZGOS.md](HALLAZGOS.md)).

La propuesta es que el conocimiento para evitarlo deje de depender de cada persona y quede en
un sistema: **macros comunes, reglas como tests, una certificación determinista y una frontera
de aprobación**, con un agente que lo aplica siempre.

---

## Qué se estandariza primero y por qué

El orden sigue el riesgo: primero lo que hoy produce números equivocados en silencio, después lo
que rompe tableros, al final lo que acelera.

| Orden | Qué | Por qué primero |
|---|---|---|
| 1 | **Staging común para la réplica CDC**: `cdc_ultima_version` (LSN), borrados, centinelas, normalización, casts visibles | Es la fuente de errores silenciosos más frecuente y aplica a todas las fuentes por igual. Un solo cambio corrige decenas de tablas |
| 2 | **Contrato y grano en cada mart publicado** | Es lo que rompe tableros. Un contrato aplicado y un test de grano son baratos y de alto impacto |
| 3 | **Reglas de negocio como tests, con dueño** | Convierte el "cuadra más o menos" en una afirmación verificable que el negocio puede firmar |
| 4 | **Certificación en CI como compuerta** | Hace obligatorio lo anterior sin depender de la revisión de cada PR |
| 5 | **Agente y skills** | Acelera cuando el estándar ya existe; antes, solo automatizaría el desorden |
| 6 | **Observabilidad operativa y FinOps** | Necesitan historia para tener umbrales que signifiquen algo |

---

## Plan de 90 días

### Días 1–30: fundación (sin bloquear a nadie)

- Repositorio plantilla con el estándar: macros, tests genéricos, política, CLI y CI.
- Inventario de fuentes replicadas y de marts publicados, con dueño de negocio y consumidores.
  Elegir **3 marts críticos** como piloto.
- Migrar el staging de las fuentes de esos 3 marts a las macros comunes.
- Certificación en CI en **modo advertencia**: se mide, no se bloquea. Esto da la línea base.
- Una sesión por persona en pareja: llevar una fuente real con la skill `nueva-fuente-a-mart`.

**Salida:** línea base de cuántos marts cumplen cada check y lista de huecos priorizada.

### Días 31–60: obligatorio para lo crítico

- La certificación **bloquea** el merge en los 3 marts piloto. Las demás reglas siguen en advertencia.
- Toda fuente nueva entra solo por el estándar (`dp new-source` + certificación).
- Reglas de negocio de los marts piloto acordadas y firmadas con sus dueños; cada una con test
  de datos, unit test y escenario de chaos.
- Environments de aprobación activos para operaciones destructivas y cambios de contrato.
- Piloto del agente con 2 personas; se mide cuánto tiempo ahorra y qué propone mal.

**Salida:** 3 productos certificados y el primer caso real de un cambio que el estándar detuvo.

### Días 61–90: escalar

- Migrar el resto de los marts críticos; los demás, conforme se toquen.
- Promover a `error` las advertencias que ya tienen historial estable (con PR y evidencia).
- Certificación programada en producción con reloj real; alertas como issues asignados al dueño.
- Líneas base de costo por producto en BigQuery; presupuestos propuestos desde esa línea base.
- Retrospectiva: qué parte del estándar se percibe como burocracia y se simplifica.

**Salida:** el estándar es la forma normal de trabajar, y su costo de seguirlo es medible.

### Roles en el equipo

| Rol | Quién | Responsabilidad |
|---|---|---|
| Dueño del estándar | Líder técnico | Política, engine, CODEOWNERS; aprueba cambios gobernados |
| Guardián rotativo | Una persona por quincena | Revisa escapes (fallas que ningún check detectó) y los convierte en escenarios de chaos |
| Ingenieros de dominio | 4 personas | Fuentes y productos de su dominio, con el agente como asistente |
| Dueños de negocio | Fuera del equipo | Firman reglas, grano y SLA de sus productos |

---

## Cómo sabremos que funciona

Se miden desde el día 1 para tener línea base; los objetivos se fijan al día 30.

| Métrica | Cómo se mide | Dirección esperada |
|---|---|---|
| Productos publicados certificados | `catalogo.json` de cada corrida de `main` | ↑ hasta 100 % de los críticos |
| Tiempo de fuente nueva a producto certificado | Del primer commit al primer `CERTIFIED` en `main` | ↓ |
| Incidentes de datos reportados por el negocio | Issues etiquetados, por mes | ↓ |
| Escapes | Incidentes que ningún check detectó (cada uno genera un escenario de chaos) | ↓, y cada uno se convierte en cobertura |
| Cobertura de reglas | Reglas con test de datos + unit test + chaos detectado (TST-09) | ↑ hasta 100 % en críticos |
| PRs que certifican al primer intento | Corridas de CI | ↑ (señal de que el estándar se entiende) |
| Tiempo de recuperación | De `DEGRADED`/`NOT_CERTIFIED` a `CERTIFIED` | ↓ |
| Costo por producto | Bytes y slot-ms por corrida desde `INFORMATION_SCHEMA.JOBS` | Estable o ↓ con más datos |

---

## Cómo cambia el diseño en BigQuery con cientos de millones de filas

En DuckDB todo se reconstruye en segundos. En BigQuery, con on-demand, **el costo lo determinan
los bytes escaneados**; con capacidad reservada, los slot-ms. El diseño cambia en cuatro puntos.

### 1. Incremental por llave en lugar de reconstruir

| Capa | Local (reto) | BigQuery |
|---|---|---|
| landing | Tabla por fuente | Particionada por día de `_airbyte_extracted_at`, clustering por la llave primaria |
| staging | Vista sobre todo landing | Incremental `merge` por llave: solo procesa las particiones de extracción nuevas más una **ventana de reproceso** (p. ej. 3 días) para cambios tardíos; borrados aplicados en el `merge` |
| silver (vigencias) | Tabla completa | Incremental: solo recalcula las llaves con versiones nuevas |
| gold | Tabla completa | Particionada por mes de embarque, clustering por planta y segmento, `require_partition_filter` |
| mart | Tabla completa | Tabla agregada pequeña (ya está exenta de partición con razón) |

La deduplicación por LSN se conserva idéntica: la macro ya está escrita con `qualify`, que
BigQuery soporta; las macros con diferencias por motor (zonas horarias, formato de mes) ya tienen
su implementación para BigQuery.

### 2. Costo: medir, presupuestar, detectar regresiones

- **Por qué importa.** Si un hecho tiene `N` filas de `B` bytes leídos por fila, reconstruirlo
  completo cada día escanea `N × B` diarios. Con partición por día y una ventana de reproceso de
  `d` días sobre `D` días de historia, el `merge` escanea del orden de `N × B × d / D`. Con años
  de historia y una ventana de días, es una reducción de dos órdenes de magnitud.
- **Medición.** Cada job de dbt se etiqueta con su nodo (`query-comment` con `job-label`), y una
  consulta diaria a `INFORMATION_SCHEMA.JOBS` atribuye bytes, slot-ms y costo a cada producto. La
  certificación ya tiene la forma: cada métrica declara su procedencia (`measured`, `estimated`,
  `not_available`). Hoy, en local, bytes y costo son `not_available`; no se simulan.
- **En el PR.** Un dry-run de BigQuery estima los bytes del modelo cambiado; una regresión fuerte
  contra la versión base se marca antes de llegar a producción.
- **Presupuestos.** Primero 30 días de línea base, después presupuestos por producto en la
  política, en `warn`; pasan a `error` solo con evidencia.
- **Consumo.** Los tableros leen marts agregados, no hechos. Si un tablero necesita detalle, se
  agrega una tabla de agregados para él, en lugar de dejar que cada visualización escanee el hecho.

### 3. Publicar sin exponer datos rotos

En el reto, si un test de un mart falla, el mart ya se escribió (así funciona `dbt build`). Los
unit tests corren antes y protegen la lógica, pero no los datos. En producción:
**write-audit-publish**: se construye en un dataset de auditoría, se certifica, y solo entonces
se publica (`dbt clone` o un intercambio de tablas). Las operaciones destructivas toman antes un
snapshot de tabla para poder revertir.

### 4. Operación

- La corrida se dispara cuando termina una sincronización de la réplica, no por horario fijo.
- La certificación corre después de cada corrida con reloj real; `DEGRADED` abre un issue al
  dueño del producto con la evidencia.
- La frescura se mide con `_airbyte_extracted_at` contra el SLA de cada producto.

---

## Riesgos de adopción

| Riesgo | Mitigación |
|---|---|
| El estándar se percibe como burocracia | Niveles: un cambio menor no exige lo mismo que un producto nuevo. CI en menos de 10 minutos. El agente hace el trabajo repetitivo |
| Falsos positivos que desgastan | Todo check nuevo empieza en advertencia y se promueve con evidencia |
| Presión por "bajar la vara" para entregar | Es un cambio gobernado: queda registrado, lo aprueba el dueño del estándar y se revisa en la retrospectiva |
| Límites del LLM gratuito | El trabajo determinista está en la CLI; el agente lee resúmenes, no tablas |
| Datos sensibles al alcance del agente | El agente trabaja con perfiles y evidencia agregada; no necesita leer filas de negocio completas. En producción, con una identidad propia y permisos de solo lectura |
| El agente actúa con credenciales humanas | Identidad propia (GitHub App) sin permisos de administración, para que no pueda saltarse la protección de rama |

---

## Lo siguiente (después de esta entrega)

| Prioridad | Qué |
|---|---|
| P1 | Regresión de KPIs certificados (base vs. head sobre los mismos datos) en CI |
| P1 | Historial de certificaciones, fichas en HTML y catálogo mínimo en GitHub Pages |
| P1 | Capa semántica en el YAML de dbt y LookML generado desde ella, con un test que compare ambos |
| P1 | Certificación programada y alertas al dueño |
| P2 | Costo de construcción y de consumo desde `INFORMATION_SCHEMA.JOBS` y la actividad de Looker |
| P2 | Write-audit-publish y snapshots antes de operaciones destructivas |
| P2 | Identidad propia del agente y catálogo de productos |
