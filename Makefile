# Punto de entrada único para personas, agente y CI.
# Todos los comandos llaman a la CLI `dp`; el Makefile solo es un atajo.

PYTHON    ?= python3
VENV      := .venv
BIN       := $(VENV)/bin
DP        := $(BIN)/dp
ESCENARIO ?= CH-01
COMPOSE   ?= docker compose

.PHONY: help setup ingest build all certify verify chaos chaos-suite test clean lock \
	docker-build docker-agente docker-shell docker-exportar

help:
	@echo "Con Docker, en cualquier máquina (Windows, macOS, Linux):"
	@echo "  docker compose run --rm dp make all    (o make docker-all; igual con test, verify, chaos…)"
	@echo "  make docker-agente  - el agente (opencode) dentro del contenedor"
	@echo "  make docker-exportar - copia la base del contenedor a ./deacero.duckdb"
	@echo ""
	@echo "make setup        - crea .venv e instala dependencias fijadas"
	@echo "make ingest       - ingiere las entregas nuevas de data/replica/"
	@echo "make build        - dbt build (modelos, tests, unit tests, contratos) + evidencia"
	@echo "make all          - ingest + build + certify"
	@echo "make certify      - certifica los productos publicados"
	@echo "make verify       - corre todo dos veces y verifica que no cambie nada"
	@echo "make chaos        - rompe algo a propósito y muestra detección, diagnóstico y recuperación"
	@echo "make chaos-suite  - verifica en sandbox que el estándar detecta las fallas del catálogo"
	@echo "make test         - pytest de las herramientas"
	@echo "make clean        - borra la base local y los artifacts generados"

ifdef DP_EN_CONTENEDOR
setup:
	@echo "Dentro del contenedor el entorno ya viene en la imagen: no hace falta make setup."
else
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements.txt
	$(BIN)/pip install --quiet -e .
	$(BIN)/python -m dp.plataforma --escribir-huella
endif

ingest:
	$(DP) ingest

build:
	$(DP) build

certify:
	$(DP) certify run

all: ingest build certify

verify:
	$(DP) verify-idempotency

chaos:
	$(DP) chaos demo $(ESCENARIO)

chaos-suite:
	$(DP) chaos run

test:
	$(BIN)/pytest -q

clean:
	rm -f *.duckdb *.duckdb.wal $(DP_DUCKDB_PATH) $(DP_DUCKDB_PATH).wal
	rm -rf dbt/target dbt/logs .evidence .certification

# Lock de la imagen (para quien mantiene el repo; requiere uv). requirements.txt sigue siendo la
# fuente de versiones; el lock fija también las dependencias indirectas, con hashes.
lock:
	uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes \
		--only-binary :all: -o requirements.lock

# Docker: atajos para quien tiene make. Sin make (p. ej. en Windows), usa directamente
# `docker compose run --rm dp make <objetivo>`. En Linux se corre con tu usuario.
DOCKER_USUARIO := $(shell [ "$$(uname -s)" = Linux ] && echo "DP_UID=$$(id -u) DP_GID=$$(id -g)")

docker-build:
	$(DOCKER_USUARIO) $(COMPOSE) build

docker-agente:
	$(DOCKER_USUARIO) $(COMPOSE) run --rm dp opencode

docker-shell:
	$(DOCKER_USUARIO) $(COMPOSE) run --rm dp bash

docker-exportar:
	$(DOCKER_USUARIO) $(COMPOSE) run --rm dp cp /datos/deacero.duckdb /workspace/deacero.duckdb
	@echo "base copiada a ./deacero.duckdb"

docker-%:
	$(DOCKER_USUARIO) $(COMPOSE) run --rm dp make $* ESCENARIO=$(ESCENARIO)
