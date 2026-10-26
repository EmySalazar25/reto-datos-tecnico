---
name: ingerir-entrega
description: Ingerir una entrega nueva de la réplica CDC, interpretar el registro de entregas y verificar que los productos siguen certificados. Usar cuando aparece una carpeta nueva en data/replica/ o piden cargar datos nuevos.
---

# Ingerir una entrega

```bash
dp ingest
dp build
dp certify run
dp certify status
```

## Cómo leer `dp ingest`

| Estado | Significa | Qué hacer |
|---|---|---|
| `cargada` | Archivo nuevo, cargado a landing | Revisar llaves nuevas/existentes y borrados |
| `ya_ingerida` | Ese archivo ya estaba cargado | Nada: la ingesta es idempotente |
| `duplicada` | Mismo contenido que otra entrega (reenvío) | Nada se carga; mencionarlo en el reporte |
| `rechazada` | Tabla no declarada, falta la llave o el archivo cambió después de ingerirse | Leer el motivo. Tabla nueva → skill `nueva-fuente-a-mart`. Archivo cambiado → las entregas son inmutables: pedir una entrega nueva |

`FALTAN columnas` o `columnas nuevas` en la salida = cambio de esquema del origen. Una
columna faltante se escala al dueño del sistema origen (no se "arregla" en el modelo); una
nueva se declara en el YAML de la fuente si el negocio la necesita.

## Después del build

- `CERTIFIED`: reporta filas nuevas por tabla y el estado de cada producto.
- `DEGRADED`: los datos recibidos rompen algo (la versión no cambió). Usa la skill
  `diagnosticar-falla`; si la causa está en el origen, redacta el escalamiento con evidencia.
- `NOT_CERTIFIED`: algo de la versión no cumple; skill `diagnosticar-falla`.

Nunca borres una entrega ni edites landing para "arreglar" datos.
