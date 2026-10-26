---
name: diagnosticar-falla
description: Diagnosticar por qué falló el pipeline o por qué un producto perdió su certificación, explicar el mecanismo (no el stack trace) y proponer el fix como pull request. Usar cuando un build falla, un test falla, o un producto queda NOT_CERTIFIED o DEGRADED.
---

# Diagnosticar una falla

## 1. Evidencia, de lo general a lo particular

```bash
dp certify status                       # qué producto y qué checks
dp certify status <producto>            # razones con evidencia mínima
dp diagnose                             # nodos que fallaron, muestra de filas, diff de unit tests, mecanismos conocidos
dp certify explain <producto> <check>   # solo si necesitas más detalle
```

Abre el SQL o YAML del archivo que señala la evidencia; no leas artifacts completos.

## 2. Distingue el tipo de falla

| Estado | Qué significa | Dónde está la causa |
|---|---|---|
| `NOT_CERTIFIED` | La versión no cumple el estándar | Código o metadata: requiere PR (o aprobación si es un cambio gobernado) |
| `DEGRADED` / `FAILED` | La versión es válida pero los datos recibidos rompen una regla | Datos u origen: puede bastar una entrega corregida; si el modelo no previó un caso real, PR |
| `DEGRADED` / `STALE` | Datos correctos pero viejos | Réplica u orquestación, no el modelo |

## 3. Explica el mecanismo

Formato obligatorio de tu respuesta:

```
Señal:            qué check o test falló (id, producto, regla)
Evidencia:        números concretos (esperado vs publicado, filas que fallan, diff)
Mecanismo:        por qué ocurre (p. ej. fan-out: el costo por viaje se repite por partida)
Causa probable:   archivo y línea, o entrega y columna
Cambio propuesto: el fix mínimo
Impacto esperado: qué números cambian y cuánto
Verificación:     qué check debe volver a PASS
```

Mecanismos conocidos: `standard/chaos/catalogo.yml` (`dp diagnose` ya los cruza con la falla).
Si no coincide con ninguno, dilo: es un hueco del estándar y merece un escenario nuevo.

## 4. Fix como PR

```bash
git switch -c fix/<descripcion-corta>
# cambio mínimo
dp build && dp certify run --context candidate && dp certify status <producto>
git add <archivos> && git commit -m "fix: <qué y por qué>"
git push -u origin fix/<descripcion-corta>
gh pr create --title "fix: ..." --body-file <archivo con el diagnóstico del paso 3>
```

- Si la falla vino de datos, agrega la entrega problemática como fixture de un unit test para
  que el caso quede cubierto.
- **Prohibido** arreglar bajando la vara: cambiar severidad, borrar o relajar tests, editar
  `standard/policy.yml` o agregar excepciones. CI lo detecta (GOV-07) y requiere aprobación humana.
- Si la causa está en el origen, no la escondas en el modelo: redacta el escalamiento con la
  evidencia y deja el producto `DEGRADED` hasta que se corrija.
