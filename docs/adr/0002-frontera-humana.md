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
| Debilitar el estándar (bajar severidad, borrar tests o reglas, editar la política) | GOV-07; requiere aprobación en `aprobacion-estandar` |
| Cambiar el motor, el CI o la configuración del agente | GOV-07 con las rutas protegidas del `CODEOWNERS` de la versión base |

La aprobación queda ligada a la **huella** del conjunto exacto de cambios gobernados (sha256 de
cada cambio con su valor antes y después), no a un nombre. El CI la registra desde la API de
GitHub. `main` reutiliza la aprobación del PR fusionado solo si calcula la misma huella; si no,
o si falta cualquier dato, la pide otra vez.

Todo lo demás (construir, probar, perfilar, inyectar chaos en un sandbox, abrir PRs) no requiere
aprobación: es el entorno de desarrollo, y lo que llegue a `main` pasa por CI.

## Consecuencias

- El agente puede ser autónomo en desarrollo sin poder dañar lo publicado.
- "Bajar la vara" para pasar un check es un cambio gobernado: el atajo más tentador para un
  agente (o una persona con prisa) queda cerrado.
- Los environments y la protección de rama no se copian en un fork:
  `scripts/configurar-github.sh` los recrea.
- Con una sola mantenedora no hay revisión de PR por otra persona: nadie podría aprobarla. Lo que
  CODEOWNERS protegía con esa revisión lo hace cumplir GOV-07 con la aprobación del environment.
- El mismo cambio no se aprueba dos veces (PR y merge), y un cambio editado después de aprobarlo
  vuelve a requerir aprobación.
- **Limitación:** el agente usa las credenciales de quien lo opera y GitHub no los distingue, por
  eso `prevent_self_review` debe quedar en `false`. Los permisos del agente niegan las rutas
  directas para aprobarse, obtener el token o hacer merge (probado con `opencode run --auto` en
  un sandbox sin credenciales), pero un agente que escribe código y lo ejecuta con herramientas
  permitidas lo hace con esa misma identidad. El cierre de fondo es una identidad propia para el
  agente (GitHub App o token sin permiso para aprobar despliegues ni administrar), en un entorno
  sin acceso a las credenciales de la persona.
