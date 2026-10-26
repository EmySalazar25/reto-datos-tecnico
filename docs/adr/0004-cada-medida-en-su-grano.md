# ADR 0004. Cada medida vive en su grano y se protege con tests de conservación

**Estado:** aceptada

## Contexto

El costo de flete es un monto por viaje y las toneladas son por partida. Unir viajes con
partidas y sumar el costo lo multiplica por el número de partidas: en `carga_1` el costo
publicado sería 2.07 veces el real, sin ningún error. Lo mismo pasa al revés: un inner join con
el maestro de clientes pierde 991 t sin avisar.

## Alternativas

1. Calcular todo en una tabla ancha a nivel partida y "dividir" el costo entre partidas.
2. Usar `count(distinct)` y trucos de agregación en el mart.
3. Separar los hechos por grano y unirlos ya agregados, con tests que comprueben que nada se
   multiplica ni se pierde.

## Decisión

Opción 3.

- `fct_viajes` (grano viaje) es el único lugar donde vive el costo; `fct_embarques` (grano
  partida) no lo lleva.
- El mart agrega cada hecho por separado a (mes, planta) y los une ya agregados.
- **Tests de conservación** (lo que entra = lo que sale): `no_fanout` compara el total de cada
  medida del mart contra el grano donde vive, con una tolerancia derivada del redondeo del
  contrato; los tests de negocio recalculan cada total desde staging con un método independiente.
- `cobertura_minima` mide cuántas filas encuentran pareja en cada join contra una dimensión.

## Consecuencias

- Un join que multiplica o pierde filas rompe un test aunque el SQL "corra".
- El patrón es reutilizable para cualquier medida de cualquier dominio; la skill
  `nueva-fuente-a-mart` lo exige.
- Hay más modelos (dos hechos en lugar de uno), a cambio de que cada uno tenga un grano
  verificable.
