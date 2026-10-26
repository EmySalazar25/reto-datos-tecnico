# ADR 0005. Stack mínimo: CLI determinista, dbt 1.10, DuckDB y un LLM gratuito

**Estado:** aceptada

## Contexto

El reto pide Python 3.9 o superior, dbt sobre DuckDB, cero costo y un LLM gratuito con sus
límites de uso. Quien evalúa clona, sigue el README y corre todo sin hablar con nadie.

## Decisión

| Pieza | Elección | Por qué |
|---|---|---|
| Transformación | dbt-core **1.10** + dbt-duckdb 1.9 | dbt 1.11 en adelante exige Python 3.10; 1.10 es la última línea compatible con el mínimo del reto y ya trae contratos y unit tests |
| Paquetes de dbt | Ninguno | Los tests genéricos son propios y cortos; evita `dbt deps` y una dependencia de red |
| Herramientas del agente | CLI `dp` en Python + Makefile | Lo pesado y lo verificable es código determinista con pruebas; el LLM gasta pocos tokens |
| Agente | opencode | Funciona con proveedores gratuitos, lee `AGENTS.md`, carga skills bajo demanda y permite permisos por comando |
| LLM | Gemini 2.5 Flash (plan gratuito de Google AI Studio) | Sin tarjeta y con una ventana de contexto amplia para un agente; se puede cambiar por Groq u Ollama sin tocar el estándar |
| MCP | No en esta entrega | La CLI ya expone todas las herramientas; un servidor MCP duplicaría la interfaz |
| CI/CD | GitHub Actions + environments | Gratis en repositorios públicos; los environments son la aprobación humana |

## Consecuencias

- `make setup` instala todo desde PyPI; no hay servicios que levantar ni credenciales.
- dbt 1.10 ya no recibe parches regulares. En producción se usaría la línea vigente con
  Python 3.10 o superior; el proyecto no usa nada específico de 1.10.
- El diseño para BigQuery (partición, clustering, macros por adaptador para fechas y zonas
  horarias) está declarado pero no se ejecuta en el reto: no se simulan métricas de BigQuery.
