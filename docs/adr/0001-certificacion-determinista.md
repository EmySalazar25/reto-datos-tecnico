# ADR 0001. La certificación es una función determinista de la evidencia

**Estado:** aceptada

## Contexto

El problema del equipo no es construir un mart, sino que cada persona entrega con un criterio
distinto y nadie se atreve a certificar el resultado. Un agente no resuelve eso si la decisión
de "esto cumple" queda en manos de su razonamiento: el mismo modelo puede responder distinto, y
un LLM gratuito puede equivocarse con confianza.

## Alternativas

1. **Checklist en documentación** que el agente o la persona revisa. Depende de que alguien se acuerde.
2. **Que el agente evalúe y dictamine.** Fácil de construir, imposible de auditar.
3. **Plataforma de observabilidad o catálogo** (servicio, base de datos, UI). Mucha infraestructura para el problema.
4. **Función determinista sobre la evidencia que ya se produce.**

## Decisión

Opción 4: `certificación = evaluate(evidencia, política)`.

- La **evidencia** es lo que el pipeline ya genera: artifacts de dbt, registro de entregas,
  reporte de idempotencia y resultados de chaos. Se guarda como snapshot en cada build.
- La **política** ([`standard/policy.yml`](../../standard/policy.yml)) define checks exigidos por
  contexto, severidades y umbrales. Es código versionado.
- El **engine** es un módulo de la CLI: collect → evaluate → aggregate → render. No es un servicio.
- Los estados se definen por **cómo se recupera el producto**: `NOT_CERTIFIED` (la versión no
  cumple: requiere un cambio o una aprobación) y `DEGRADED` (la versión es válida, la operación
  no: se recupera con una corrida sana).
- La evidencia que falta es `UNKNOWN` y nunca cuenta como PASS.
- El agente **lee** la certificación (`status`, `explain`); no la escribe.

## Consecuencias

- Misma evidencia, misma política y misma versión del engine dan el mismo resultado; el JSON
  registra los tres (`evidence_digest`, `policy_digest`, `engine_version`).
- El estándar generaliza: el engine no tiene lógica de ningún dominio; se prueba con un producto
  sintético de mantenimiento.
- La ficha de certificación es también la checklist de un producto nuevo: los checks en FAIL
  dicen exactamente qué falta.
- Un test de datos que falla puede deberse al código o a los datos. Se resuelve por contexto
  (`data_tests_phase` en la política): en operación juzga los datos; en una versión candidata o en
  CI, el código. Este ajuste salió del chaos CH-03, que reveló una atribución equivocada.
