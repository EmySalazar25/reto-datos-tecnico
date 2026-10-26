# Convenciones de la plataforma de datos (resumen)

Esto es lo que hoy está escrito. Que exista no significa que alguien lo siga: ese es el problema.

## Arquitectura por capas (medallion)

```
Sistemas origen (SQL Server, SAP, APIs)
    ↓ réplica (Airbyte CDC / Datastream)
landing_*   → datos tal cual llegan: texto, con historia de versiones
    ↓ dbt
staging     → 1:1 con la fuente: tipado, renombrado, limpieza y deduplicación. Sin lógica de negocio.
    ↓ dbt
silver_*    → entidades limpias e integradas, lógica reutilizable (int_)
    ↓ dbt
gold_*      → modelo dimensional certificado: hechos (fct_) y dimensiones (dim_)
    ↓ dbt
mart_*      → tablas por área de negocio, listas para BI (Looker)
```

## Nombres de modelos dbt

| Prefijo | Capa | Ejemplo |
|---|---|---|
| `stg_<fuente>__<entidad>` | Staging | `stg_fle__viajes` |
| `int_<entidad>__<verbo/detalle>` | Silver | `int_viajes__pesajes` |
| `fct_<proceso>` | Gold | `fct_embarques` |
| `dim_<entidad>` | Gold | `dim_cliente` |
| (nombre de negocio) | Mart | `embarques_mensual` |

- Nombres de columnas en `snake_case` y en español, como el negocio las nombra (`cla_planta`, `fecha_embarque`).
- Siempre `ref()` y `source()`: nunca nombres de tablas escritos a mano.

## Git

- Commits en inglés con *Conventional Commits*: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Ramas: `feature/<descripcion>`, `fix/<descripcion>`.

## Producción (contexto)

En producción el destino es **BigQuery** y dbt corre orquestado (dbt Cloud / Composer). Para este reto se usa DuckDB para que no necesites credenciales, pero diseña pensando en BigQuery: en volúmenes grandes el costo lo determinan los bytes escaneados.
