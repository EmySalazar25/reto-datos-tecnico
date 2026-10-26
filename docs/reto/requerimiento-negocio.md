# Requerimiento — Tablero de desempeño de embarques

| | |
|---|---|
| **Solicitante** | Dirección de Logística |
| **Área de datos** | Equipo de Ingeniería de Datos |
| **Prioridad** | Alta |
| **Consumidor** | Tablero en Looker (lo construye BI a partir del mart) |

## Lo que nos pidieron (en palabras del negocio)

> "Cada lunes en la junta de dirección cada planta trae su Excel y nunca cuadran las toneladas ni el costo de flete. Queremos **una sola fuente** que responda:
>
> 1. ¿Cuántas **toneladas** embarcó cada planta por mes, en cuántos **viajes**, y cuánto nos costó el **flete por tonelada**?
> 2. ¿Qué **% de las toneladas** llegan **a tiempo** al cliente? Lo queremos por **segmento de cliente** (Distribuidor, Constructora, Industrial)."

## Reglas de negocio acordadas con Logística

1. **Fecha de embarque.** Usar `FechaRealEmbarque`. Cuando no esté capturada, usar `FechaEmbarqueFinal`. Todos los reportes se agrupan por esta fecha, en hora local de planta.
2. **Qué cuenta como embarcado.** Solo los viajes **en tránsito** (`TRA`) o **entregados** (`ENT`). Los programados (`PRO`) todavía no salen, y los cancelados (`CAN`) nunca salieron.
3. **Toneladas.** Se usa el **peso documentado** de las partidas del viaje (no el de báscula). 1 tonelada = 1,000 kg.
4. **Costo de flete.** Es un monto **por viaje**, en MXN.
5. **A tiempo.** Un viaje llega a tiempo si la fecha de entrega del POD (comprobante de entrega) es **menor o igual** a la fecha compromiso. Solo se evalúan los viajes que ya tienen POD. Un viaje puede llevar partidas de varios clientes: cada partida hereda la puntualidad de su viaje.
6. **Segmento del cliente.** Logística reasigna el segmento de algunos clientes a lo largo del año. El indicador debe usar el segmento que tenía el cliente **el día del embarque**, no el actual. El cambio aplica desde el día en que se registra.
7. **Clientes no identificados.** Si una partida trae un cliente que no existe en el maestro, sus toneladas **no se pierden**: se reportan en el segmento `NO_IDENTIFICADO`.

## Lo que NO sabemos todavía

- Cómo quiere BI filtrar por región: por ahora no es parte del alcance.
- Si en el futuro habrá más plantas en Estados Unidos.
- Más adelante Logística va a pedir indicadores de básculas de planta (todavía no está la réplica).

Si alguna regla no te queda clara, toma la interpretación que te parezca más razonable y documéntala como supuesto.
