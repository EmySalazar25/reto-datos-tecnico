# Diccionario de datos — capa landing

*Documento proporcionado por los equipos de los sistemas origen. Última actualización: 2025.*

Todas las tablas landing se cargan con **Airbyte CDC** desde SQL Server. Cada fila representa una **versión** de un registro del origen: cuando el registro cambia en el origen, llega una fila nueva. Todas las columnas llegan como texto.

### Columnas de control (presentes en todas las tablas)

| Columna | Descripción |
|---|---|
| `_ab_cdc_lsn` | Log Sequence Number de SQL Server del cambio. |
| `_ab_cdc_updated_at` | Fecha y hora (UTC) en que se registró el cambio en el origen. |
| `_ab_cdc_deleted_at` | Fecha y hora (UTC) en que se eliminó el registro en el origen. Vacío si no está eliminado. |
| `_airbyte_extracted_at` | Fecha y hora (UTC) en que Airbyte extrajo la fila. |

---

## landing_fle.fle_viaje — Viajes de embarque

| Columna | Tipo origen | Descripción |
|---|---|---|
| `IdViaje` | int | Identificador del viaje (PK). |
| `ClaPlanta` | int | Planta que embarca. FK a `opc_planta`. |
| `FechaCompromiso` | datetime | Fecha comprometida de entrega al cliente. |
| `FechaRealEmbarque` | datetime | Fecha y hora en que el camión salió de planta. Nulo si no se capturó. |
| `FechaEmbarqueFinal` | datetime | Fecha de cierre del documento de embarque. |
| `Estatus` | char(3) | `PRO` programado, `TRA` en tránsito, `ENT` entregado, `CAN` cancelado. |
| `CostoFlete` | money | Costo del flete del viaje en MXN. |

Fechas en hora local de planta (America/Monterrey).

## landing_fle.fle_viaje_det — Partidas del viaje

| Columna | Tipo origen | Descripción |
|---|---|---|
| `IdViaje` | int | FK a `fle_viaje`. |
| `IdPartida` | int | Consecutivo de la partida dentro del viaje. |
| `ClaCliente` | int | Cliente destino de la partida. FK a `vta_cliente`. |
| `ClaArticulo` | int | Artículo embarcado. |
| `PesoKg` | decimal | Peso documentado de la partida, en kilogramos. |

## landing_fle.fle_entrega — Comprobante de entrega (POD)

| Columna | Tipo origen | Descripción |
|---|---|---|
| `IdViaje` | int | Viaje entregado (PK). |
| `FechaEntrega` | datetime | Fecha y hora de entrega firmada por el cliente (hora local). |

El POD lo captura el área de Tráfico cuando recibe el documento físico firmado.

## landing_vta.vta_cliente — Maestro de clientes

| Columna | Tipo origen | Descripción |
|---|---|---|
| `ClaCliente` | int | Identificador del cliente (PK). |
| `NomCliente` | varchar | Razón social. |
| `Segmento` | varchar | `DISTRIBUIDOR`, `CONSTRUCTORA` o `INDUSTRIAL`. |
| `ClaEstado` | varchar | Estado de la república (o de EE.UU.) del cliente. |

## landing_opc.opc_planta — Catálogo de plantas

| Columna | Tipo origen | Descripción |
|---|---|---|
| `ClaPlanta` | int | Identificador de la planta (PK). |
| `NomPlanta` | varchar | Nombre de la planta. |
| `ClaPais` | char(2) | País. |
