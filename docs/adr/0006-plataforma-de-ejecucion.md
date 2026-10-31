# ADR 0006. La plataforma de ejecución se detecta en el setup y se verifica en cada corrida

**Estado:** propuesta (guarda mínima implementada; ver [Estado en esta entrega](#estado-en-esta-entrega))

## Contexto

En una Mac con Apple Silicon, `make chaos` puede fallar en el paso 4, cuando el agente toma el
control, si el agente no es nativo:

```
ImportError: dlopen(.../_duckdb...-darwin.so): ... incompatible architecture
(have 'arm64', need 'x86_64')
```

El mecanismo:

1. `make setup` corre en una terminal nativa. El Python de python.org es *universal2* y arranca
   como `arm64`, así que pip instala las ruedas `arm64` de las librerías compiladas (`duckdb`).
2. Si opencode está instalado con el Homebrew de Intel (prefijo `/usr/local`), su binario es
   `x86_64` y corre traducido por Rosetta 2.
3. Los procesos que lanza un programa traducido prefieren la mitad `x86_64` de un binario
   universal. El agente ejecuta `.venv/bin/dp`, Python arranca como `x86_64` y no puede cargar
   la extensión `arm64`.
4. El agente recibe un traceback en lugar de un mecanismo, no puede usar `dp` y la falla
   inyectada queda en el árbol de trabajo.

Nada lo detecta hoy: el README pide "Python 3.9, Git y make" sin hablar de plataforma, `dp` no
sabe para qué plataforma se instaló su entorno y el CI solo corre en `ubuntu-latest` (x86_64).

El caso es parte de una clase de fallas: Linux `aarch64` frente a `x86_64`, un `.venv` copiado
entre máquinas, un Python actualizado después del setup, Windows nativo (sin `make` y con
`.venv\Scripts`). pip ya elige la rueda correcta **al instalar**; el problema es que la
plataforma de instalación y la de ejecución no coinciden, y que una versión fijada podría no
publicar rueda para alguna plataforma (pip intentaría compilarla desde fuente).

## Alternativas

1. **Documentarlo en el README.** Depende de que alguien lo lea antes de que falle.
2. **Forzar la arquitectura en el Makefile** (`arch -arm64 ...`). Solo cubre macOS y no cubre los
   procesos que lanza el agente.
3. **Ruedas universal2.** Depende de que cada librería las publique y no cubre Linux.
4. **Contenedor (Docker o devcontainer).** Fija el runtime de Python, pero agrega un requisito
   pesado (Docker Desktop requiere licencia de pago en empresas grandes), contradice el
   [ADR 0005](0005-stack-minimo.md) y no resuelve el caso observado: el agente sigue corriendo en
   el host salvo que también se meta al contenedor, y en Apple Silicon una imagen `amd64` corre
   emulada.
5. **Detectar la plataforma en el setup, instalar con el lock de esa plataforma, guardar su huella
   y verificarla en cada corrida.**

## Decisión

Opción 5. El contenedor queda como posibilidad futura y opcional: sería una plataforma más
(`linux-<arch>`) con su propio lock, sin cambiar esta decisión.

| Pieza | Qué hace |
|---|---|
| Detector (`src/dp/plataforma.py`) | Solo biblioteca estándar; no importa nada compilado. Devuelve una etiqueta canónica (`macos-arm64`, `macos-x86_64`, `linux-x86_64`, `linux-aarch64`) a partir del SO y de la arquitectura **del proceso**, y aparte la del hardware y si corre traducido (macOS: `sysctl -n hw.optional.arm64` y `sysctl -n sysctl.proc_translated`) |
| Plataformas soportadas | Las cuatro anteriores. Windows nativo no: el setup lo rechaza y recomienda WSL2 |
| Versiones por plataforma | `requirements.in` es la única fuente de versiones (las de hoy). De ahí se generan `requirements/<etiqueta>.txt` con hashes. Si una plataforma necesita otra versión, se expresa con un marcador PEP 508 en `requirements.in` con su justificación. `make lock` regenera todos |
| `make setup` | 1) Corre el detector con el Python del sistema. 2) Falla con un mensaje accionable si la plataforma no está soportada, si Python es menor a 3.9 o si el proceso corre traducido por Rosetta en hardware `arm64`. 3) Instala el lock de la plataforma con `--require-hashes --only-binary=:all:`, nunca desde fuente. 4) Escribe la huella en `.venv/dp-plataforma.json` (etiqueta, versión de Python, lock usado y su sha256). 5) Termina con `dp doctor` |
| Guarda en `dp` | Antes de importar cualquier módulo con extensiones compiladas, compara la plataforma del proceso con la huella. Si no coinciden, sale con el código `4` (entorno inválido, [ADR 0007](0007-como-se-consume-el-agente.md)) y un mensaje con **mecanismo**: "el entorno se instaló para `macos-arm64` y este proceso corre como `macos-x86_64` (traducido por Rosetta); lo lanzó un programa `x86_64`, p. ej. opencode de Intel; instala la versión nativa". Sin huella, pide correr `make setup` |
| `dp doctor` | Reporte breve (y `--json`): plataforma, traducción, Python, huella del entorno, `dbt` y `duckdb` importables y opencode (ruta, versión mínima 1.19 y arquitectura del binario). Cada renglón con `OK`, `ADVERTENCIA` o `ERROR` y su remedio |
| `dp chaos demo`, paso 4 | Antes de lanzar opencode, verifica que su binario pueda correr como la arquitectura de la huella. Si no, no lo lanza: muestra el diagnóstico y restaura de forma determinista, como hoy cuando opencode no está instalado. Una demo nunca deja la falla inyectada |
| Contexto del agente | `AGENTS.md`: si `dp` sale con el código de plataforma, el agente no intenta repararlo (en particular, no corre `make setup` desde un proceso traducido); reporta el mensaje a la persona |
| CI | Matriz de `make setup`, `make test` y `make all` en Linux x86_64, Linux arm64 y macOS arm64 (y macOS Intel mientras GitHub ofrezca el runner). En macOS arm64, una prueba corre `dp` con `arch -x86_64` y espera el código de plataforma. Otra verifica que los locks correspondan a `requirements.in` |

## Consecuencias

- Una plataforma equivocada se detecta en el setup o aparece como un diagnóstico de una línea, no
  como un traceback, igual que cualquier otra falla del estándar.
- Un agente lanzado con la arquitectura equivocada sigue sin poder trabajar, pero el sistema lo
  explica y la demo se recupera sola. Corregirlo (instalar opencode nativo) es acción de la persona.
- No hay dependencias nuevas en ejecución: el detector y la guarda son biblioteca estándar y
  cuestan milisegundos. Generar los locks requiere una herramienta de desarrollo (`pip-tools` o
  `uv`) solo para quien mantiene el repo; quien evalúa no la necesita.
- Subir una versión obliga a regenerar todos los locks; el CI falla si alguno quedó desfasado.
- El CI tarda más por los runners de macOS (gratuitos en repositorios públicos).
- Los cambios en `.github/` y `AGENTS.md` son rutas protegidas: entran con GOV-07
  ([ADR 0002](0002-frontera-humana.md)).
- Complementa el [ADR 0005](0005-stack-minimo.md): el stack no cambia, solo se declara en qué
  plataformas corre y se verifica.

## Estado en esta entrega

Implementado, porque cubre el caso descrito sin cambiar cómo se instalan las dependencias:

| Pieza | Cómo quedó |
|---|---|
| Detector | `src/dp/plataforma.py`, solo biblioteca estándar: etiqueta del proceso, Rosetta, hardware y arquitecturas de un ejecutable Mach-O o ELF |
| Huella | `make setup` escribe `.venv/dp-plataforma.json` (etiqueta y versión de Python) |
| Guarda en `dp` | Punto de entrada `dp.entrada`: compara el proceso con la huella y traduce el error de importar `duckdb` con otra arquitectura. Sale con `4` y el mecanismo, y le pide a un agente no repararlo. **Sin huella no bloquea**, para no romper entornos anteriores |
| Demo de chaos | Revisa la arquitectura de opencode antes de lanzarlo. **Restaura la falla inyectada siempre** que el agente no recertifique, no arranque, no pueda correr en la plataforma o la demo se interrumpa |

Pendiente (P1): el *preflight* de `make setup` (plataforma no soportada, Python menor a 3.9,
Rosetta), los locks con hashes, `make lock`, `dp doctor`, la regla en `AGENTS.md` y la matriz de
CI.

## Notas de revisión

Verificado el 31 de octubre de 2026, antes de implementar los locks:

- **Las versiones fijadas tienen ruedas en las cuatro plataformas**, con Python 3.9 y 3.13:
  `--only-binary=:all:` es viable hoy.
- **La resolución cambia según la versión de Python**, no solo según la plataforma: por ejemplo,
  `dbt-adapters` resuelve a 1.17.3 con Python 3.9 y a 1.24.5 con 3.10 o superior. Un lock por
  plataforma generado para 3.9 forzaría versiones viejas a quien usa 3.13. Se recomienda **un
  solo lock universal** (`uv pip compile --universal --python-version 3.9 --generate-hashes
  --only-binary :all:`), que expresa esas diferencias con marcadores y cubre las cuatro
  plataformas en un archivo.
- **La demo debe restaurar ante cualquier falla del agente, no solo la de plataforma.** Observado:
  con el modelo gratuito, el agente intentó un comando fuera de su lista permitida, `opencode run`
  lo rechazó y terminó la corrida sin corregir; antes de esta entrega, la falla inyectada habría
  quedado en el árbol.
- La prueba con `arch -x86_64` requiere Rosetta en el runner de macOS arm64; verificarlo al
  implementar la matriz.
