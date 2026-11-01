# Entorno reproducible del estándar (ADR 0008): el mismo Linux, el mismo Python y las mismas
# dependencias exactas en cualquier máquina (Windows, macOS Intel o Apple Silicon, Linux).
# La imagen es nativa en x86_64 y arm64, sin emulación, y el agente corre dentro: agente, dp y
# duckdb siempre tienen la misma arquitectura.
#
#   docker compose build
#   docker compose run --rm dp make all

# python:3.12-slim-bookworm, fijada por digest (índice multiplataforma: amd64 y arm64).
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git make \
    && rm -rf /var/lib/apt/lists/* \
    # El repo se monta desde la máquina con otro dueño: git debe aceptarlo (lo usan dp y chaos).
    && git config --system --add safe.directory '*'

# opencode, versión validada, verificada por sha256 para cada arquitectura.
ARG TARGETARCH
ARG OPENCODE_VERSION=1.19.4
ARG OPENCODE_SHA256_AMD64=849bd6b3d959a1d2ef200ed1634a51c79a45ca236aa26665d75debd694805cce
ARG OPENCODE_SHA256_ARM64=8568230ccd847dc93e95b9f6894379077d3e014a16b48040743573e77c23e85f
RUN set -eu; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
        amd64) arch=x64; sha="$OPENCODE_SHA256_AMD64" ;; \
        arm64) arch=arm64; sha="$OPENCODE_SHA256_ARM64" ;; \
        *) echo "arquitectura no soportada: ${TARGETARCH:-desconocida} (se soportan amd64 y arm64)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/opencode.tar.gz \
        "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${arch}.tar.gz"; \
    echo "${sha}  /tmp/opencode.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin opencode; \
    rm /tmp/opencode.tar.gz

# Dependencias exactas: lock con hashes y solo ruedas, nunca compiladas desde fuente.
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv \
    && pip install --require-hashes --only-binary=:all: -r /tmp/requirements.lock

# El paquete dp en modo editable: el código que se monta en /workspace es el que corre.
COPY pyproject.toml /workspace/pyproject.toml
COPY src /workspace/src
RUN pip install --no-deps -e /workspace \
    && python -m dp.plataforma --escribir-huella

COPY docker/entrada.sh /usr/local/bin/entrada.sh
RUN chmod 0755 /usr/local/bin/entrada.sh \
    # Escribibles por cualquier usuario: en Linux se corre con el usuario de la máquina.
    && mkdir -p /datos /home/dp \
    && chmod 1777 /datos /home/dp

ENV DP_EN_CONTENEDOR=1 \
    DP_DUCKDB_PATH=/datos/deacero.duckdb \
    HOME=/home/dp
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrada.sh"]
CMD ["make", "help"]
