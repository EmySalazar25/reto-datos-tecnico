"""Ejecuta dbt con la configuración del repo (perfil, proyecto y base local)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dp import paths


def dbt_env() -> dict:
    env = dict(os.environ)
    env["DP_DUCKDB_PATH"] = str(paths.DUCKDB_PATH)
    env["DBT_PROFILES_DIR"] = str(paths.DBT_DIR)
    env.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    return env


def run_dbt(args: list) -> int:
    dbt_bin = Path(sys.executable).parent / "dbt"
    cmd = [str(dbt_bin), *args, "--project-dir", str(paths.DBT_DIR)]
    return subprocess.call(cmd, env=dbt_env(), cwd=str(paths.ROOT))
