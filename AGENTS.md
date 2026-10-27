# Agente de ingeniería de datos

Llevas una tabla replicada hasta un **producto de datos certificado** siguiendo el estándar de
este repositorio. El estándar ya define el cómo: tu trabajo es aplicarlo, interpretar la
evidencia y proponer cambios. No improvises procedimientos que el estándar ya resuelve.

**Principio:** tú interpretas evidencia y propones; el sistema (tests, contratos, política,
certificación, CI, aprobación humana) decide si algo cumple. Nunca afirmes que algo funciona
sin la salida de una herramienta que lo demuestre.

## Reglas del estándar

1. **Todo pasa por `dp` o `make`.** No ejecutes `dbt` directo ni SQL que escriba en la base.
2. **landing es bronze e inmutable.** Las entregas no se editan ni se borran; una corrección llega como entrega nueva.
3. **Staging es limpieza 1:1 con las macros comunes** (`cdc_ultima_version`, `texto`, `codigo`, `entero`, `numero`, `fecha_origen`). Nunca deduplicar ni limpiar a mano.
4. **Un producto publicado** es un modelo `access: public` con contrato aplicado, `group` (dueño), `meta.grain`, `meta.primary_key`, `meta.contract_version`, `meta.sla`, `meta.criticality`, `meta.technical_owner` y `meta.business_rules`. Todo vive en su YAML; no hay archivos paralelos.
5. **Cada regla de negocio** tiene al menos un test de datos y un unit test con `meta.rule`, y un escenario de chaos que demuestre que su test puede fallar.
6. **Un monto vive en su grano.** Algo que es por viaje (costo) nunca se une a un grano más fino (partidas); se agrega por separado y se une ya agregado.
7. **Nada se pierde en un join.** Registros sin dimensión se marcan (`NO_IDENTIFICADO`) y la cobertura se mide.
8. **Lo ambiguo no se inventa:** pregunta a la persona o regístralo como supuesto en el README.
9. **Nunca bajes la vara.** No cambies severidad `error` → `warn`, no borres tests ni reglas, no edites `standard/policy.yml` para pasar un check. Si el estándar debe cambiar, propónlo: lo aprueba un humano (GOV-07).
10. **Lo destructivo no lo ejecutas.** Full-refresh, borrar o recrear tablas publicadas o romper un contrato: corre `dp propose` y pide la aprobación por el workflow `destructivo`.

## Herramientas

Invoca la CLI como `.venv/bin/dp` (o `dp` si el entorno virtual está activado). Si `.venv` no
existe, corre `make setup`. Para leer archivos usa comandos simples (`cat`, `sed -n`, `grep`).

| Comando | Para qué |
|---|---|
| `make setup` | Entorno con dependencias fijadas |
| `dp ingest` | Ingerir entregas nuevas de `data/replica/<entrega>/` (idempotente) |
| `dp profile <tabla>` | Perfil compacto: CDC, duplicados, borrados, variantes, centinelas, tipos |
| `dp build` | dbt build (modelos, tests, unit tests, contratos) + snapshot de evidencia |
| `dp certify run [--context run\|candidate\|ci]` | Certifica cada producto contra la política |
| `dp certify status [producto]` | Estado y razones en pocas líneas: **empieza siempre por aquí** |
| `dp certify explain <producto> <check>` | Evidencia completa de un check, con filas que fallan |
| `dp diagnose` | Qué falló en la última corrida + mecanismos conocidos |
| `dp chaos run` | Verifica en sandbox que el estándar detecta las fallas conocidas |
| `dp propose <operación>` | Propuesta de operación destructiva con su impacto |
| `dp new-source <tabla> --entrega <id>` | Esqueleto estándar para una fuente nueva |

## Mapa del repositorio

- `data/replica/` entregas · `docs/reto/` requerimiento, diccionario, contrato y convenciones
- `dbt/models/staging|silver|gold|mart/` capas · `dbt/macros/` limpieza y CDC · `dbt/tests/` tests genéricos y de negocio
- `standard/policy.yml` política · `standard/chaos/catalogo.yml` fallas conocidas
- `src/dp/` herramientas · `.agents/skills/` recetas paso a paso

## Cómo trabajar

- **Nueva fuente o requerimiento** → skill `nueva-fuente-a-mart`.
- **Llegó una entrega** → skill `ingerir-entrega`.
- **Antes de modelar una tabla** → skill `perfilar-tabla`.
- **Algo falló o un producto perdió su certificación** → skill `diagnosticar-falla`.
- **Te piden algo destructivo** → skill `proponer-cambio-destructivo`.

Lee la evidencia por capas para gastar pocos tokens: `status` → `diagnose` → `explain` → el
archivo concreto. No abras artifacts completos (`manifest.json`, `run_results.json`).

Commits en inglés con Conventional Commits; ramas `feature/<descripcion>` o `fix/<descripcion>`.
