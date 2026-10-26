"""Ejecuta dbt con la configuración del repo (perfil, proyecto y base local)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dp import paths


def dbt_env(db_path: Path | None = None, project_dir: Path | None = None) -> dict:
    env = dict(os.environ)
    env["DP_DUCKDB_PATH"] = str(db_path or paths.DUCKDB_PATH)
    env["DBT_PROFILES_DIR"] = str(project_dir or paths.DBT_DIR)
    env.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    return env


def run_dbt(args: list, project_dir: Path | None = None, db_path: Path | None = None, quiet: bool = False) -> int:
    project_dir = project_dir or paths.DBT_DIR
    dbt_bin = Path(sys.executable).parent / "dbt"
    cmd = [str(dbt_bin), *args, "--project-dir", str(project_dir)]
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(cmd, env=dbt_env(db_path, project_dir), cwd=str(project_dir.parent), stdout=out, stderr=out)
