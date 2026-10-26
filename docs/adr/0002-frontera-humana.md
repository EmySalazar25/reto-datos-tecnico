# ADR 0002. Dónde está la frontera de aprobación humana

**Estado:** aceptada

## Contexto

El reto exige que lo destructivo pase por aprobación humana ("si el agente puede tirar tablas
solo, no cuenta") y pide justificar dónde está la frontera. Un agente opera con las herramientas
que se le dan; un permiso local se puede editar.

## Alternativas

1. **Instrucciones en el contexto del agente.** Depende de que obedezca.
2. **Permisos del agente** (denegar comandos). Útil, pero es un archivo del repo que cualquiera edita.
3. **Aprobación en el servidor** (environments de GitHub, CODEOWNERS, compuerta de CI).
4. **Aprobación para todo** lo que haga el agente. Vuelve inútil al agente.

## Decisión

La frontera está en **lo que cambia lo publicado o debilita el estándar**, y vive en el servidor.
Las opciones 1 y 2 se mantienen como primeras barreras, no como la frontera.

| Operación | Mecanismo |
|---|---|
| Full-refresh, borrar o recrear tablas publicadas | Workflow `destructivo`: solicitar es libre; ejecutar espera a un revisor en `produccion-destructiva`. `dp build --full-refresh` se niega fuera de ese job |
| Romper un contrato | GOV-07 compara columnas y tipos contra la versión base; requiere aprobación en `aprobacion-estandar` |
| Debilitar el estándar (bajar severidad, borrar tests o reglas, editar la política) | GOV-07 + CODEOWNERS |

Todo lo demás (construir, probar, perfilar, inyectar chaos en un sandbox, abrir PRs) no requiere
aprobación: es el entorno de desarrollo, y lo que llegue a `main` pasa por CI.

## Consecuencias

- El agente puede ser autónomo en desarrollo sin poder dañar lo publicado.
- "Bajar la vara" para pasar un check es un cambio gobernado: el atajo más tentador para un
  agente (o una persona con prisa) queda cerrado.
- Los environments y la protección de rama no se copian en un fork:
  `scripts/configurar-github.sh` los recrea.
- **Limitación:** hoy el agente usa las credenciales de quien lo opera. En un equipo debe tener
  identidad propia (GitHub App) sin permisos de administración, para que no pueda saltarse la
  protección de rama.
