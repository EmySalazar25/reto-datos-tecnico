# ADR 0008. Un contenedor es el camino reproducible; la instalación nativa sigue soportada

**Estado:** aceptada

## Contexto

Quien evalúa clona el repo y lo corre en una máquina que no conocemos: Windows, macOS con Intel
o Apple Silicon, Linux x86_64 o arm64, con cualquier versión de Python y su propio opencode.

La instalación nativa supone cosas que no se cumplen en todas:

- **Windows nativo** no tiene `make`, el entorno virtual vive en `.venv\Scripts` y Git convierte
  los finales de línea a CRLF al clonar, lo que rompe el Makefile y los scripts.
- **La versión de Python** cambia la resolución de dependencias: con 3.9 y con 3.13 se instalan
  versiones indirectas distintas ([ADR 0006](0006-plataforma-de-ejecucion.md), notas de revisión).
- **El agente puede tener otra arquitectura** que el entorno: un opencode `x86_64` bajo Rosetta
  lanza `dp` como `x86_64` y no puede cargar el `duckdb` `arm64` (ADR 0006, contexto).

El ADR 0006 detecta y explica estas fallas, pero no las evita: la persona sigue teniendo que
arreglar su máquina antes de poder evaluar.

## Alternativas

1. **Solo la instalación nativa con guardas** (ADR 0006). Explica la falla en una línea, pero no
   la evita, y Windows queda fuera salvo dentro de WSL2.
2. **Contenedor con Python y dependencias, y el agente en el host.** El agente tendría que llamar
   a `docker compose run` en lugar de `dp`, lo que cambia sus comandos y sus permisos, y seguiría
   dependiendo del opencode que cada persona tenga instalado.
3. **Contenedor con el agente dentro.** Un solo entorno con el sistema, Python, dependencias y
   agente fijados.
4. **devcontainer o GitHub Codespaces.** Cero instalación local, pero requiere VS Code o una
   cuenta de GitHub, y es una capa sobre la misma imagen: no sustituye a la alternativa 3.
5. **Imagen publicada en un registro.** Evita construirla (1 a 2 minutos), pero agrega publicar y
   firmar en cada versión; construirla desde el `Dockerfile` fijado siempre corresponde al commit
   que se está evaluando.

## Decisión

Alternativa 3, como camino recomendado. La instalación nativa (`make setup`) se mantiene en
macOS y Linux, con la guarda del ADR 0006.

| Pieza | Qué hace |
|---|---|
| Imagen base | `python:3.12-slim-bookworm`, fijada por digest. Su índice es multiplataforma: Docker elige la variante nativa de la máquina (amd64 o arm64), nunca una emulada |
| Dependencias | `requirements.lock`, generado desde `requirements.txt` con `uv pip compile --universal --python-version 3.12 --generate-hashes --only-binary :all:`: las 59 dependencias, directas e indirectas, con versión y hash. Se instala con `--require-hashes --only-binary=:all:`, nunca compilando desde fuente. `requirements.txt` sigue siendo la fuente de versiones; `make lock` regenera el lock |
| Agente | opencode 1.19.4 dentro de la imagen, descargado del release oficial y verificado por sha256 para cada arquitectura. El agente, `dp` y `duckdb` comparten arquitectura por construcción: el caso del ADR 0006 no puede ocurrir |
| Comando | `docker compose run --rm dp make <objetivo>`, igual en PowerShell, cmd, macOS y Linux. Con `make` en la máquina, `make docker-<objetivo>` |
| Repositorio | Se monta en `/workspace` y `dp` se instala como paquete editable: corre el código del árbol de trabajo, así que una corrección (de la persona o del agente) aplica sin reconstruir la imagen |
| Base de datos | En un volumen de Docker (`/datos/deacero.duckdb`), no en la carpeta montada: en Windows y macOS ese disco compartido es lento y el bloqueo de archivos de DuckDB no es confiable ahí. `make docker-exportar` la copia a `./deacero.duckdb` |
| `.venv` de la máquina | Se oculta con un directorio en memoria y se llena con enlaces al entorno de la imagen: `.venv/bin/dp`, que usan el Makefile, las skills y el agente, funciona igual, y un entorno creado en otro sistema nunca se ejecuta en el contenedor |
| Finales de línea | `.gitattributes` fija LF para código y configuración en cualquier sistema; las entregas de la réplica se conservan byte por byte, como llegaron del origen |
| Permisos | En Linux, y con el repo clonado dentro de WSL2, se corre con el usuario de la máquina (`DP_UID` y `DP_GID`; los atajos `make docker-*` los ponen solos). Con el repo en una carpeta de Windows o de macOS, Docker Desktop ya deja los archivos a nombre de la persona |
| Huella | La imagen registra su plataforma (`linux-x86_64` o `linux-aarch64`, Python 3.12): la guarda del ADR 0006 también aplica dentro |
| CI | Job `contenedor`: construye la imagen y corre `make test`, `make all`, `make verify` y `make chaos-suite` en x86_64 y en arm64, con el usuario del runner |

### Relación con el ADR 0006

El ADR 0006 previó el contenedor como "una plataforma más (`linux-<arch>`) con su propio lock,
sin cambiar esta decisión", y eso es lo que se implementa aquí. Sus objeciones a la alternativa
del contenedor, revisadas:

| Objeción | Ahora |
|---|---|
| Agrega un requisito pesado; Docker Desktop requiere licencia de pago en empresas grandes | Sigue siendo cierto, y por eso la instalación nativa se mantiene. Docker Desktop es gratuito para uso personal, educativo y en empresas pequeñas; Docker Engine en Linux (también dentro de WSL2) no requiere licencia |
| Contradice el [ADR 0005](0005-stack-minimo.md) | El stack no cambia: las mismas versiones de dbt, DuckDB y opencode. El contenedor solo fija el sistema y el Python que las ejecutan |
| El agente sigue corriendo en el host | Corre dentro del contenedor |
| En Apple Silicon una imagen `amd64` corre emulada | La imagen se construye en cada máquina para su arquitectura nativa; no se distribuye una imagen de una sola arquitectura |

## Consecuencias

- Una sola instrucción en cualquier máquina. En ese camino no pueden ocurrir las fallas de
  plataforma conocidas: falta de `make`, finales de línea CRLF, otra versión de Python, un agente
  de otra arquitectura o un `.venv` copiado de otro sistema.
- Requisito: Docker con Compose v2. La primera construcción tarda de 1 a 2 minutos con red y la
  imagen ocupa unos 880 MB.
- El contenedor usa Python 3.12; el CI sigue probando la instalación nativa con 3.9, el mínimo
  que pide el reto, y con 3.13.
- El agente dentro del contenedor no tiene las credenciales de GitHub ni de git de la máquina:
  diagnostica, corrige y recertifica, pero no puede hacer push ni abrir PRs; eso lo hace la
  persona. La frontera humana ([ADR 0002](0002-frontera-humana.md)) no depende de esto, pero se
  refuerza. Su configuración y sus sesiones no persisten entre corridas; una llave propia se pasa
  con `-e`.
- **Windows no se puede probar en el CI:** los runners de Windows de GitHub solo corren
  contenedores Windows. La cobertura es por construcción: el contenedor es el mismo Linux que el
  CI prueba en x86_64; un clon con la conversión de finales de línea de Windows
  (`core.autocrlf=true`) deja todo el código en LF y las entregas idénticas, y certifica igual
  dentro del contenedor; y la base no vive en el disco compartido.
- `requirements.lock` se regenera cuando cambia `requirements.txt` (`make lock`, requiere `uv`
  solo para quien mantiene el repo).
- El job `contenedor` no es obligatorio para fusionar: una caída de los runners arm64 no debe
  bloquear un cambio. La certificación que decide sigue siendo la del job `certificacion`.

## Pendiente (P1)

- Que el CI falle si `requirements.lock` no corresponde a `requirements.txt`.
- `devcontainer.json` sobre esta misma imagen, para abrir el repo en Codespaces sin instalar nada.
- Lock con hashes para la instalación nativa y el resto del ADR 0006 (`dp doctor`, *preflight*
  de `make setup`, CI en macOS).
