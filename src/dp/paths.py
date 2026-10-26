"""Rutas del repositorio. Todo se resuelve desde la raíz para no depender del cwd."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("DP_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = Path(os.environ.get("DP_DATA_DIR", ROOT / "data" / "replica"))
DBT_DIR = ROOT / "dbt"
EVIDENCE_DIR = ROOT / ".evidence"
# El contrato de los marts fija el nombre del archivo DuckDB.
DUCKDB_PATH = Path(os.environ.get("DP_DUCKDB_PATH", ROOT / "deacero.duckdb"))
