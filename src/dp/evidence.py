"""Snapshot de evidencia.

Después de cada build se guarda en `.evidence/` exactamente lo que la certificación va a leer:
artifacts de dbt, registro de entregas y metadatos de la corrida. La certificación nunca lee
la base ni `dbt/target` directamente: evalúa este snapshot, así el resultado es reproducible.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

DBT_ARTIFACTS = ("manifest.json", "run_results.json")
EVIDENCE_FILES = (
    "manifest.json",
    "run_results.json",
    "entregas.json",
    "build.json",
    "idempotencia.json",
    "chaos_resultados.json",
)
# Lo que determina el resultado de un build: el código de dbt y las entregas de la réplica.
BUILD_INPUTS = ("dbt/models", "dbt/macros", "dbt/tests", "dbt/dbt_project.yml", "data/replica")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"no serializable: {type(value)}")


def git_commit(root: Path) -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root, stderr=subprocess.DEVNULL)
        dirty = subprocess.call(["git", "diff", "--quiet", "HEAD"], cwd=root, stderr=subprocess.DEVNULL) != 0
        return sha.decode().strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "sin-git"


def dump_registry(db_path: Path) -> list:
    if not db_path.exists():
        return []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        exists = con.execute(
            "select count(*) from information_schema.tables where table_schema = 'ops' and table_name = 'entregas'"
        ).fetchone()[0]
        if not exists:
            return []
        cur = con.execute("select * from ops.entregas order by ingerido_en, id_entrega, archivo")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()
    for r in rows:
        for key in ("columnas_observadas", "columnas_faltantes", "columnas_nuevas"):
            r[key] = json.loads(r[key]) if r.get(key) else []
    return rows


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def snapshot_build(evidence_dir: Path, dbt_dir: Path, db_path: Path, root: Path, exit_code: int, started_at: str) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name in DBT_ARTIFACTS:
        src = dbt_dir / "target" / name
        if src.exists():
            shutil.copy2(src, evidence_dir / name)
    write_json(evidence_dir / "entregas.json", dump_registry(db_path))
    write_json(
        evidence_dir / "build.json",
        {"comando": "dbt build", "codigo_salida": exit_code, "inicio": started_at, "fin": utc_now(), "commit": git_commit(root),
         "entradas": inputs_digest(root)},
    )


def inputs_digest(root: Path) -> str:
    """Huella del código de dbt y de las entregas: si cambia, la última construcción ya no los refleja."""
    h = hashlib.sha256()
    for rel in BUILD_INPUTS:
        base = root / rel
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = sorted(p for p in base.rglob("*") if p.is_file())
        else:
            files = []
        for path in files:
            h.update(path.relative_to(root).as_posix().encode())
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
    return "sha256:" + h.hexdigest()


def evidence_digest(evidence_dir: Path) -> str:
    """Huella de la evidencia: sha256 sobre (nombre, sha256 del archivo) en orden fijo."""
    h = hashlib.sha256()
    for name in EVIDENCE_FILES:
        path = evidence_dir / name
        if path.exists():
            h.update(name.encode())
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
    return "sha256:" + h.hexdigest()


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
