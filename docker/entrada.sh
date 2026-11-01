#!/bin/sh
# Entrada del contenedor. compose.yaml cubre el `.venv` del repo con un directorio vacío en
# memoria: un entorno creado en otra máquina (macOS, Windows) nunca se ejecuta aquí. Se llena con
# enlaces al entorno de la imagen, así `.venv/bin/dp`, `make` y el agente funcionan igual que en
# una instalación nativa.
set -eu

if [ -d /workspace/.venv ] && [ -z "$(ls -A /workspace/.venv 2>/dev/null)" ]; then
    for entrada in /opt/venv/*; do
        ln -s "$entrada" "/workspace/.venv/$(basename "$entrada")"
    done
fi

exec "$@"
