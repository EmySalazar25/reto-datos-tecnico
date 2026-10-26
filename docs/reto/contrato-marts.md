# Contrato de los marts — esquema `mart_logistica`

BI construirá el tablero directamente sobre estas tablas, así que esto es lo único que está fijo. Cómo llegas a ellas es decisión tuya. Los **nombres de tabla y de columna** son exactos y no negociables, y **el grano debe respetarse**: una fila por llave. Puedes agregar columnas extra si te son útiles.

Todas las tablas deben quedar en el esquema **`mart_logistica`** de `deacero.duckdb`. Ojo: por defecto dbt antepone el esquema del *target* (`main_mart_logistica`).

Tipos: `texto`, `entero`, `decimal`. Redondeo: toneladas a 3 decimales, dinero y porcentajes a 2.

---

## 1. `embarques_mensual`

**Grano:** una fila por `anio_mes` × `cla_planta`.

| Columna | Tipo | Definición |
|---|---|---|
| `anio_mes` | texto | Mes de la fecha de embarque, formato `YYYY-MM`. |
| `cla_planta` | entero | Planta. |
| `nom_planta` | texto | Nombre de la planta. |
| `num_viajes` | entero | Viajes embarcados. |
| `toneladas_embarcadas` | decimal | Suma del peso documentado ÷ 1,000. |
| `costo_flete_mxn` | decimal | Suma del costo de flete de los viajes. |
| `costo_flete_por_ton` | decimal | `costo_flete_mxn / toneladas_embarcadas`. |

## 2. `cumplimiento_entrega`

**Grano:** una fila por `anio_mes` × `segmento_cliente`.

| Columna | Tipo | Definición |
|---|---|---|
| `anio_mes` | texto | Mes de la fecha de embarque, `YYYY-MM`. |
| `segmento_cliente` | texto | `DISTRIBUIDOR`, `CONSTRUCTORA`, `INDUSTRIAL` o `NO_IDENTIFICADO`. Segmento vigente el día del embarque. |
| `toneladas_entregadas` | decimal | Toneladas de partidas cuyo viaje ya tiene POD. |
| `toneladas_a_tiempo` | decimal | De las anteriores, las entregadas a tiempo. |
| `pct_a_tiempo` | decimal | `100 * toneladas_a_tiempo / toneladas_entregadas` (0 a 100). |
