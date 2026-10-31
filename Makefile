# Punto de entrada único para personas, agente y CI.
# Todos los comandos llaman a la CLI `dp`; el Makefile solo es un atajo.

PYTHON    ?= python3
VENV      := .venv
BIN       := $(VENV)/bin
DP        := $(BIN)/dp
ESCENARIO ?= CH-01

.PHONY: help setup ingest build all certify verify chaos chaos-suite test clean

help:
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

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements.txt
	$(BIN)/pip install --quiet -e .
	$(BIN)/python -m dp.plataforma --escribir-huella

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
	rm -f *.duckdb *.duckdb.wal
	rm -rf dbt/target dbt/logs .evidence .certification
