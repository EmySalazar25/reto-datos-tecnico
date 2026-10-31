# ADR 0007. Cómo se consume el agente: un contrato en `dp` y tres tipos de cliente

**Estado:** propuesta (no implementada en esta entrega; ver [Notas de revisión](#notas-de-revisión))

## Contexto

El estándar debe poder usarlo, además de quien lo construyó:

- **Otro agente** (un orquestador, un asistente corporativo, un pipeline) que necesita certificar,
  diagnosticar o proponer sin leer la documentación.
- **Una persona de datos junior** sin contexto, que no conoce el reto, CDC, dbt ni las siglas de la
  política.

Lo que existe hoy:

| Aspecto | Estado actual |
|---|---|
| Interfaz principal | Conversación con opencode dentro del repo; `AGENTS.md` envía cada petición a una skill |
| Herramientas | CLI `dp`, determinista. Salida JSON solo en `dp diagnose --json`, `dp profile --json` y `dp certify explain`. `status`, `certify run`, `ingest`, `build`, `propose` y `chaos` devuelven texto; `build` imprime el log completo de dbt |
| Artefactos | `.certification/<producto>.json` (con `schema_version`) y `catalogo.json`: ya son un contrato de lectura, pero no está documentado como tal |
| Códigos de salida | Inconsistentes: `certify status <producto>` devuelve 0 aunque el producto esté `NOT_CERTIFIED`; `certify run` devuelve 1; `certify gate` usa 3 para "requiere aprobación"; `build` usa 2 para la operación negada; sin certificación previa, algunos comandos terminan con `SystemExit(mensaje)` |
| Otro agente | Solo puede analizar texto de `dp` o lanzar `opencode run` (un LLM dentro de otro, con salida en texto libre y permisos en `ask` que nadie responde) |
| MCP | Descartado "en esta entrega" por el [ADR 0005](0005-stack-minimo.md) |
| Persona junior | El README (unos 25 KB) está escrito para un evaluador del reto. No hay guía de primeros pasos ni glosario. Las respuestas usan TST-06, LSN, fan-out o DEGRADED sin traducir. Muchos comandos piden confirmación y nadie le dice qué aprobar |

La frontera humana ([ADR 0002](0002-frontera-humana.md)) ya protege lo publicado para cualquier
cliente. Lo que falta es que cada cliente pueda usar el estándar sin depender de quien lo
construyó.

## Alternativas

1. **Mantener la conversación con opencode como única interfaz.** Sirve a una persona con
   contexto; a un agente lo obliga a analizar texto, y a un junior lo deja sin punto de partida.
2. **Usar `opencode run` como API para otros agentes.** Paga el costo de un LLM dos veces, devuelve
   texto libre y el resultado depende del razonamiento del sub-agente.
3. **Servicio HTTP.** Contradice el [ADR 0005](0005-stack-minimo.md) (sin servicios que levantar).
4. **Contrato estable en la CLI `dp` y clientes delgados encima.**

## Decisión

Opción 4. `dp` es el producto; opencode es uno de sus clientes. Los tres tipos de cliente usan
las mismas herramientas deterministas y ninguno puede saltarse la frontera humana.

```
              ┌── persona junior ── opencode + guía de primeros pasos
dp (contrato) ┼── otro agente ───── MCP (stdio) o dp --json
              └── CI ────────────── dp --json + códigos de salida
```

### 1. Contrato de máquina de `dp`

**`--json` en todos los comandos**, no solo en algunos, con un sobre común:

```json
{
  "contrato": "dp/1",
  "comando": "certify status",
  "ok": false,
  "codigo_salida": 1,
  "resultado": { "...": "..." },
  "explicacion": "embarques_mensual no está certificado: una regla de negocio (costo por viaje) no se cumple.",
  "siguiente": ["dp certify explain embarques_mensual TST-06"]
}
```

- `explicacion` es una frase en lenguaje llano.
- `siguiente` contiene comandos exactos: el cliente no tiene que adivinar el paso siguiente.
- Con `--json`, la salida estándar lleva solo el JSON. Los logs (incluido el de dbt) van a la
  salida de error y a `.evidence/logs/`.

**Códigos de salida** únicos, documentados y probados:

| Código | Significa | Ejemplos |
|---|---|---|
| 0 | Éxito; el resultado cumple | Todo CERTIFIED, entrega cargada |
| 1 | El comando corrió, pero el resultado no cumple | NOT_CERTIFIED, test que falla, entrega rechazada |
| 2 | Uso incorrecto u operación negada por el estándar | Argumentos inválidos, `build --full-refresh` fuera del workflow |
| 3 | Requiere aprobación humana | Cambio gobernado GOV-07, propuesta destructiva pendiente |
| 4 | Entorno inválido | Plataforma distinta a la del setup ([ADR 0006](0006-plataforma-de-ejecucion.md)), `.venv` ausente |
| 5 | Falta evidencia previa | No hay certificación: corre `dp certify run` |

`certify status <producto>` pasa a devolver 1 si el producto no está certificado. Así un agente
puede decidir solo con el código de salida.

**`dp capacidades --json`**: el catálogo de comandos que el propio `dp` publica. Para cada uno:
argumentos; si solo lee, si escribe en el entorno local o si requiere aprobación; los códigos que
puede devolver. Es lo primero que lee un agente nuevo.

**Esquemas versionados** de cada salida JSON y de `.certification/*.json` en `docs/contrato-cli/`.
Las pruebas validan que cada salida cumpla su esquema. Un cambio incompatible sube la versión
(`dp/2`) y es una ruta protegida en CODEOWNERS (GOV-07): otros agentes dependen de ese contrato
igual que el tablero depende del de un mart.

### 2. Servidor MCP delgado (`dp mcp`)

- **Transporte:** stdio, local, dentro del repo. Cada herramienta llama a la misma función que el
  comando de `dp` y devuelve el mismo sobre JSON.
- **Herramientas expuestas:**
  - de solo lectura: `capacidades`, `doctor`, `certify_status`, `certify_explain`, `diagnose`,
    `profile`, `chaos_list`;
  - de desarrollo local: `ingest`, `build` (sin `--full-refresh`), `certify_run`, `chaos_run`
    (sandbox), `new_source`;
  - de propuesta: `propose` (no ejecuta nada; la ejecución sigue en el workflow destructivo).
- **No se exponen:** `chaos inject` y `chaos restore`, que modifican el árbol de trabajo;
  `verify-proposal` y `execute-proposal`, que son exclusivas del CI; y cualquier forma de
  full-refresh.
- **Dependencia:** el SDK de MCP es una dependencia opcional (`pip install -e .[mcp]`) y exige
  Python 3.10 o superior. El núcleo sigue funcionando con 3.9.
- **Relación con el ADR 0005:** su decisión "MCP: no en esta entrega" queda sustituida por esta.

### 3. opencode como sub-agente: soportado, no como API

`opencode run "<tarea>"` sirve para delegar una tarea completa, por ejemplo "diagnostica y abre el
PR con la corrección". Quien delega nunca toma por buena la respuesta en texto del sub-agente:
verifica el resultado con `dp certify status --json` o con el CI. Es el principio del estándar
aplicado entre agentes: el LLM propone, el sistema decide.

### 4. Entrada para una persona junior

- **`make doctor`** ([ADR 0006](0006-plataforma-de-ejecucion.md)): lo primero que corre; le dice
  si su entorno sirve y qué hacer si no.
- **`docs/PRIMEROS-PASOS.md`**, una sola página:
  - instalar y verificar;
  - 5 frases tipo ("llegó una entrega", "esto falló", "quiero un indicador nuevo", "revisa esta
    tabla", "necesito borrar o recargar todo"), con la skill que dispara cada una y lo que verá;
  - qué significa terminar (CERTIFIED);
  - qué aprobar y qué nunca aprobar cuando opencode pide confirmación;
  - nunca usar `--auto`.
- **`make tutorial`**: `make chaos` presentado como recorrido guiado, con una pausa y una
  explicación en lenguaje llano por paso.
- **`docs/glosario.md`**: cada sigla de la política (TST-\*, OBS-\*, GOV-\*), cada estado y cada
  término (CDC, LSN, fan-out, SCD2, grano) en una o dos líneas. `explicacion` y `dp certify status`
  usan esas mismas definiciones, tomadas de una sola fuente.
- **Regla nueva en `AGENTS.md`:** si la persona no da contexto, el agente responde en lenguaje
  llano, traduce cada código la primera vez que aparece y termina con el siguiente paso concreto.

## Consecuencias

- Un agente externo puede descubrir, ejecutar y decidir sin leer la documentación ni analizar
  texto. Un junior tiene un punto de partida y sabe qué significa "terminado".
- La salida de texto para personas no cambia: el JSON es opt-in.
- Cambia el código de salida de `certify status <producto>` (de 0 a 1 si no está certificado).
  Hay que revisar los scripts y workflows que lo usan.
- Hay más superficie que mantener: esquemas y pruebas de contrato por comando.
- El servidor MCP solo existe con Python 3.10 o superior. Quien use 3.9 consume `dp --json`.
- Un agente que use MCP actúa con las credenciales de quien lo lanza: aplica la misma limitación
  del [ADR 0002](0002-frontera-humana.md), y la frontera sigue en el servidor (environments de
  GitHub).
- Los cambios en `AGENTS.md`, `.agents/`, `.github/` y los esquemas del contrato son rutas
  protegidas: entran con GOV-07.

## Notas de revisión

Verificado contra el repo el 31 de octubre de 2026, para quien la implemente:

- **Ningún workflow depende del código de salida de `certify status`**; solo lo leen las skills y
  `AGENTS.md`. Cambiarlo a 1 para un producto no certificado es seguro para el CI.
- **La prueba de `tests/test_certify.py` que espera `SystemExit` no trata la falta de
  certificación**: verifica que `--aprobado-por` ya no exista (argparse, uso incorrecto, código 2).
  Debe conservarse tal cual.
- **Una certificación desactualizada** (ya detectada por `dp certify status` desde esta entrega)
  encaja en el código 5, "falta evidencia vigente: corre `dp certify run`". `certify gate` conserva
  0, 1 y 3, como esperan los workflows.
- **El código 4 ya existe:** lo usa la guarda de plataforma del
  [ADR 0006](0006-plataforma-de-ejecucion.md).
- **`dp doctor`, mientras no exista, no debe reportar OK:** un resultado provisional dice
  "pendiente". Afirmar que algo funciona sin la herramienta que lo demuestre contradice el
  principio del estándar.
