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
| Full-refresh, borrar o recrear tablas publicadas | Workflow `destructivo`: solicitar es libre; el sistema sella una propuesta (sha256) con clasificación y recomendación deterministas; ejecutar espera a un revisor en `produccion-destructiva` (solo desde ramas protegidas) y ejecuta solo la propuesta cuyo hash coincide con el revisado. `dp build --full-refresh` se niega siempre, sin excepciones por variable de entorno: la única ruta es `dp execute-proposal` dentro de ese job |
| Romper un contrato | GOV-07 compara columnas y tipos contra la versión base; requiere aprobación en `aprobacion-estandar` |
| Debilitar el estándar (bajar severidad, borrar tests o reglas, editar la política) | GOV-07; requiere aprobación en `aprobacion-estandar` |
| Modificar o borrar una entrega de la réplica | GOV-07: las entregas son de solo agregar. Una entrega nueva entra libre; modificar o borrar un archivo que ya estaba en la versión base requiere aprobación en `aprobacion-estandar` |
| Cambiar el motor, el CI, la configuración de cualquier agente o el contenedor | GOV-07 con las rutas protegidas del `CODEOWNERS` de la versión base |
| Llegar a `main` | Protección de rama con `enforce_admins`: los checks requeridos valen también para administradores; sin push directo ni `--admin` |

### Guardrails y controles: el agente puede cambiar, las garantías no

Las reglas que viven en la configuración de un cliente (`opencode.json`, los permisos de Claude
Code o de Cursor, las instrucciones de `AGENTS.md`) son **guardrails**: detienen errores temprano
y le explican al agente qué no hacer, pero cada cliente las aplica distinto y todas se pueden
evadir (otra forma del mismo comando, un modo automático, otro cliente). Se conservan, pero
ninguna garantía depende solo de ellas. Las garantías viven en **controles** que no dependen del
cliente: `dp`, los tests, la certificación, el CI, la protección de `main`, los environments y el
alcance de la credencial que recibe el agente.

La aprobación queda ligada a la **huella** del conjunto exacto de cambios gobernados (sha256 de
cada cambio con su valor antes y después), no a un nombre. El CI la registra desde la API de
GitHub. `main` reutiliza la aprobación del PR fusionado solo si calcula la misma huella; si no,
o si falta cualquier dato, la pide otra vez.

Para lo destructivo, la persona decide con información: el estado actual de cada producto en dos
dimensiones (certificación de lo publicado e integridad frente a la reconstrucción desde
landing), la clasificación y el riesgo de la propuesta, el impacto y una recomendación
determinista que es informativa. La IA puede explicar; la clasificación, la recomendación, el
hash, la verificación, la autorización y la ejecución son deterministas.

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
- En una operación destructiva, aprobar la propuesta A nunca ejecuta B: el job que ejecuta
  recalcula el hash de la propuesta descargada y falla cerrado ante cualquier diferencia. Si se
  rechaza, el job nunca arranca; un job de solo lectura deja la evidencia de la decisión.
- En CI no hay una producción persistente: el incidente `INC-01` que justifica un full-refresh en
  la demostración se simula sobre la copia de lo publicado, y la propuesta lo declara.
- **Credencial del agente.** En el contenedor ([ADR 0008](0008-contenedor-reproducible.md)) el
  agente no ve la sesión de `gh` ni el `GH_TOKEN` de la persona: solo recibe, si la persona lo
  define, un token de grano fino con Contents y Pull requests. Según los permisos de GitHub, sin
  Deployments no puede aprobar un environment, sin Administration no puede tocar la protección ni
  los environments, sin Actions de escritura no puede disparar el workflow destructivo y sin
  Workflows no puede empujar cambios al CI. `scripts/verificar-credencial-agente.sh` lo
  comprueba con sondas inocuas contra el repositorio real.
- **Limitación: una sola cuenta.** Ese token pertenece a la misma persona que revisa, así que
  `prevent_self_review` sigue en `false` (con `true` nadie podría aprobar) y GitHub atribuye los
  PRs del agente a esa persona. Con Contents de escritura el token también puede fusionar un PR
  cuyos checks requeridos pasen; un cambio gobernado sigue esperando la aprobación humana del
  check `aprobacion`.
- **Limitación: instalación nativa.** Fuera del contenedor el agente corre con la sesión completa
  de `gh` de la persona; ahí, no aprobarse ni fusionar depende de los guardrails del cliente. Por
  eso el camino recomendado para el agente es el contenedor.
- El cierre de fondo es una identidad propia para el agente (GitHub App o cuenta de servicio sin
  rol de revisor ni de administración). Con ella, `prevent_self_review: true` y la revisión
  obligatoria del PR vuelven a ser posibles.
- **Limitación: el CI de un PR corre con la versión del PR.** Un PR que modifica el workflow o el
  motor se juzga con esa versión modificada; hoy lo cierra el merge humano (y el token del agente
  no puede empujar cambios al CI). Correr la gobernanza desde la versión base queda pendiente.
- **Limitación: las pruebas de las herramientas no están gobernadas.** Un PR puede cambiar o borrar
  pruebas de `tests/` (las de `dp`) sin aprobación humana; los tests de dbt sí lo están (GOV-07
  detecta tests borrados o con severidad rebajada). Gobernar todo `tests/` convertiría cada ajuste
  normal de pruebas en una aprobación. Pendiente (P1): gobernar solo el borrado de pruebas.
