---
name: perfilar-tabla
description: Perfilar una tabla de la réplica antes de modelarla para encontrar llaves reales, versiones CDC, duplicados, borrados, valores sucios, fechas centinela y tipos. Usar antes de crear o cambiar un modelo de staging, o cuando un número no cuadra.
---

# Perfilar una tabla

```bash
dp profile <tabla>            # p. ej. fle_viaje, vta_cliente, staging.stg_fle__viajes
dp profile <tabla> --json     # si necesitas procesar el resultado
```

## Qué buscar y qué decide cada hallazgo

| Señal en el perfil | Implica | Mecanismo del estándar |
|---|---|---|
| `hasta N versiones por llave` (N > 1) | Es historia CDC, no estado | `cdc_ultima_version` en staging; `cdc_versiones` si se necesita la historia |
| `filas duplicadas exactas` | Reenvíos de la réplica | La deduplicación por llave + LSN los absorbe |
| `llaves borradas hoy` | Registros eliminados en el origen | Se excluyen después de elegir la última versión; test `excluye_borrados` |
| `empate de timestamp (solo el LSN ordena)` | `_ab_cdc_updated_at` no basta para ordenar | El desempate es por LSN numérico (ya está en la macro) |
| `con_espacios`, `variantes_por_mayusculas_o_espacios` | Códigos sucios | Macro `codigo()` + `accepted_values` |
| `fecha_centinela_1900` | Fecha no capturada en SQL Server | Macro `fecha_origen()`; test `sin_fecha_centinela` |
| `no_convierten_a_numero/fecha` | Valores que un cast seguro volvería nulos | Test `castea_a` en la fuente; reportarlo como hallazgo |
| `tipo_probable` | Tipo destino del cast en staging | `entero()`, `numero()`, `fecha_origen()` |

Confirma la llave primaria: una llave real tiene `llaves_distintas` = estados vigentes. Si
dudas, pregunta; una llave equivocada duplica o pierde filas en todo lo que sigue.

Lo que encuentres y nadie te dijo es un **hallazgo**: anótalo con qué viste, cómo lo
detectaste, impacto en el negocio, cómo se resolvió y qué se escala al dueño del origen.
