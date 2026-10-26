---
name: nueva-fuente-a-mart
description: Llevar una fuente replicada nueva y un requerimiento de negocio hasta un producto de datos certificado (mart publicado con contrato, reglas como tests y certificación). Usar cuando llega una tabla que no está declarada o un indicador nuevo.
---

# De fuente nueva a producto certificado

El objetivo no es "que corra": es que `dp certify status <producto>` diga `CERTIFIED`.
La lista de checks que fallan es tu checklist.

## 1. Ficha del requerimiento (antes de escribir SQL)

Extrae del requerimiento y escribe en el PR:

| Campo | Pregunta |
|---|---|
| Producto | ¿Qué tabla publicada se pide? Nombre de negocio, en español, snake_case |
| Indicadores | Fórmula exacta y unidad de cada uno |
| Grano | ¿Una fila por qué? Es la llave del producto |
| Dueño | ¿Qué área responde por el número? (se vuelve `group`) |
| Reglas | Cada regla de negocio, numerada (R1, R2…) |
| Consumidor | ¿Qué tablero o proceso lo usa? (se vuelve `exposure`) |
| SLA | ¿Para cuándo debe estar listo? |

**Lo que falte, pregúntalo.** Si no hay a quién, decide lo más razonable y regístralo como
supuesto en el README. Nunca inventes un dueño ni una regla.

## 2. Fuente

1. Copia la entrega en `data/replica/<entrega>/` (un CSV por tabla).
2. `dp new-source <tabla> --entrega <entrega> --sistema <sistema>` genera:
   el YAML de la fuente (columnas + `meta.primary_key` a confirmar) y el modelo de staging.
3. Confirma la llave primaria real con `dp profile <tabla>` (skill `perfilar-tabla`).
4. `dp ingest` y `dp build --select +stg_<sistema>__<entidad>`.

## 3. Capas

- **staging** (`stg_<sistema>__<entidad>`): solo macros comunes, 1:1, sin reglas de negocio.
  Tests: unicidad de la llave (`tags: [engineering]`), `excluye_borrados`, `castea_a` en la
  fuente, `accepted_values` para códigos normalizados.
- **silver** (`int_<entidad>__<detalle>`): reglas reutilizables (vigencias SCD2 desde el CDC,
  filtros de negocio). Si una dimensión cambia en el tiempo, construye la vigencia desde las
  versiones CDC (`cdc_versiones`), no con `dbt snapshot`.
- **gold** (`fct_`, `dim_`): cada medida en su grano. Declara `meta.grain`, `partition_by` y
  `cluster_by` en hechos.
- **mart** (`mart/<dominio>/`): el producto. Copia la forma de
  `dbt/models/mart/logistica/_logistica__models.yml`: `group`, `access: public`,
  `contract.enforced`, `data_type` por columna y todo el `meta`.

## 4. Reglas → tests

Por cada regla Rn:
1. **Test de datos** en `dbt/tests/negocio/rn_<regla>.sql` con
   `config(tags=['business'], meta={'rule': 'Rn'})`. Recalcula lo esperado **desde staging**,
   con un método distinto al del modelo, y devuelve filas solo si no coincide.
2. **Unit test** con un fixture que reproduzca la trampa aunque los datos de hoy no la traigan.
3. **Escenario de chaos** en `standard/chaos/catalogo.yml` que rompa la regla; corre
   `dp chaos run <ID>` y confirma `DETECTADO`.
4. `no_fanout` sobre cada medida del mart contra el grano donde vive; `cobertura_minima` en
   cada join contra una dimensión.

## 5. Certificar

```bash
dp build
dp certify run --context candidate     # juzga la versión, como lo hará CI
dp certify status <producto>
```

Repite hasta `CERTIFIED`. Si un check falla, léelo con `dp certify explain`. No bajes
severidades ni quites tests para pasar (regla 9 de AGENTS.md).

## 6. PR

Rama `feature/<producto>`, commits pequeños, y en el cuerpo del PR: la ficha del paso 1, los
supuestos y el resumen de `.certification/resumen.md`.
