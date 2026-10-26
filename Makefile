# Punto de entrada único para personas, agente y CI.
# Todos los comandos llaman a la CLI `dp`; el Makefile solo es un atajo.

PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin
DP     := $(BIN)/dp

.PHONY: help setup ingest build all test clean

help:
	@echo "make setup   - crea .venv e instala dependencias fijadas"
	@echo "make ingest  - ingiere las entregas nuevas de data/replica/"
	@echo "make build   - corre dbt build (modelos + tests + contratos)"
	@echo "make all     - ingest + build"
	@echo "make test    - pytest de las herramientas"
	@echo "make clean   - borra la base local y los artifacts generados"

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements.txt
	$(BIN)/pip install --quiet -e .

ingest:
	$(DP) ingest

build:
	$(DP) build

all: ingest build

test:
	$(BIN)/pytest -q

clean:
	rm -f *.duckdb *.duckdb.wal
	rm -rf dbt/target dbt/logs .evidence .certification
