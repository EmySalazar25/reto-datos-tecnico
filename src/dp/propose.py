"""Propuesta de operación destructiva: el agente propone, el sistema explica, una persona decide.

No ejecuta nada destructivo. Reúne la evidencia de cada producto afectado en dos dimensiones
distintas y deja que las reglas deterministas de `dp.certify.propuesta` clasifiquen, recomienden
y sellen la propuesta:

- Certificación de lo publicado: los tests, contratos y reglas corridos sobre lo publicado.
- Integridad de la publicación: si lo publicado coincide con la reconstrucción determinista
  desde landing (INTACT) o no (DRIFTED).

En este repo no hay una producción persistente: lo publicado es una copia de la reconstrucción
de esta corrida. Un incidente simulado (solo en dev o CI) altera esa copia para demostrar la
detección; la propuesta lo declara como simulación.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import duckdb

from dp import dbt_runner, evidence, paths
from dp.certify import propuesta as gov
from dp.idempotency import table_fingerprints

OPERATIONS = {
    "full-refresh": "Reconstruir todas las capas desde landing, descartando lo publicado.",
    "recrear-producto": "Borrar y volver a crear una tabla publicada fuera de la corrida normal.",
    "cambio-contrato": "Quitar o renombrar columnas, cambiar tipos o grano de un producto publicado.",
}
INCIDENTS = {
    "INC-01": {
        "descripcion": "se borraron fuera del pipeline las filas del último mes de `mart_logistica.embarques_mensual`",
        "sql": "delete from mart_logistica.embarques_mensual "
               "where anio_mes = (select max(anio_mes) from mart_logistica.embarques_mensual)",
    },
}
SIMULATION_NOTE = ("Es una simulación sobre la copia de lo publicado en CI/dev, no una producción persistente; "
                   "en producción, el plan leería el estado real del warehouse.")
POLICY = paths.ROOT / "standard" / "policy.yml"


def simulate_incident(db_path: Path, incident_id: str) -> dict:
    from dp.chaos import guard

    guard()  # solo en dev o CI
    incident = INCIDENTS[incident_id]
    con = duckdb.connect(str(db_path))
    try:
        con.execute(incident["sql"])
    finally:
        con.close()
    return {"id": incident_id, "descripcion": incident["descripcion"], "nota": SIMULATION_NOTE}


def integrity(published_db: Path, rebuild_db: Path, relations: list) -> dict:
    """INTACT si la tabla publicada es idéntica (filas y contenido) a la reconstrucción desde landing."""
    published, rebuilt = table_fingerprints(published_db), table_fingerprints(rebuild_db)
    result = {}
    for rel in relations:
        a, b = published.get(rel), rebuilt.get(rel)
        if a is None or b is None:
            state = "UNKNOWN"
        else:
            state = "INTACT" if a == b else "DRIFTED"
        result[rel] = {"integridad": state, "filas_publicadas": a and a["filas"], "filas_reconstruccion": b and b["filas"]}
    return result


def certify_published(published_db: Path, work_dir: Path, evidence_dir: Path) -> dict:
    """Certificación de lo publicado: los tests de dbt corren sobre la copia publicada, no sobre la reconstrucción."""
    from dp.certify import engine

    target = work_dir / "target"
    dbt_runner.run_dbt(["test", "--target-path", str(target)], db_path=published_db, quiet=True)
    built = evidence.load_json(evidence_dir / "run_results.json") or {"results": []}
    tested = evidence.load_json(target / "run_results.json") or {"results": []}
    by_id = {r["unique_id"]: r for r in built.get("results", [])}
    for r in tested.get("results", []):
        by_id[r["unique_id"]] = r
    ev = work_dir / "evidencia"
    ev.mkdir(parents=True, exist_ok=True)
    shutil.copy2(evidence_dir / "manifest.json", ev / "manifest.json")
    evidence.write_json(ev / "run_results.json", {"metadata": tested.get("metadata"), "results": list(by_id.values())})
    evidence.write_json(ev / "entregas.json", evidence.dump_registry(published_db))
    evidence.write_json(ev / "build.json", evidence.load_json(evidence_dir / "build.json") or {})
    result = engine.certify(ev, POLICY, context="run")
    return {p["product"]["id"]: p["status"] for p in result["products"]}


def _commit() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=paths.ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        return "sin-git"


def plan(operation: str, product: str | None, reason: str, evidence_dir: Path, cert_dir: Path, db_path: Path,
         incident: str | None = None) -> dict:
    if operation not in OPERATIONS:
        raise ValueError(f"operación desconocida: {operation}. Opciones: {', '.join(OPERATIONS)}")
    manifest = evidence.load_json(evidence_dir / "manifest.json")
    if manifest is None or not db_path.exists():
        raise ValueError("no hay construcción: corre `dp build` y `dp certify run` antes de proponer")
    public = {n["name"]: n for n in manifest.get("nodes", {}).values() if n.get("resource_type") == "model" and n.get("access") == "public"}
    if operation in ("recrear-producto", "cambio-contrato"):
        if not product or product not in public:
            raise ValueError(f"indica --producto con un producto publicado: {', '.join(sorted(public))}")
        targets = [product]
    else:
        targets = sorted(public)
    rebuilt = {p["product"]: p["status"] for p in (evidence.load_json(cert_dir / "catalogo.json") or {"products": []})["products"]}

    # Lo publicado: una copia de la reconstrucción de esta corrida (con el incidente simulado, si se pidió).
    work_dir = evidence_dir / "publicado"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    # Mismo nombre de archivo: DuckDB toma de él el nombre del catálogo y las vistas lo referencian.
    published_db = work_dir / db_path.name
    shutil.copy2(db_path, published_db)
    condition = simulate_incident(published_db, incident) if incident else None
    relations = {name: f"{public[name].get('schema')}.{public[name].get('alias') or name}" for name in targets}
    integ = integrity(published_db, db_path, list(relations.values()))
    published_cert = certify_published(published_db, work_dir, evidence_dir)

    exposures = manifest.get("exposures", {})
    affected = []
    for name in targets:
        node = public[name]
        meta = node.get("meta") or {}
        affected.append({
            "producto": name, "relacion": relations[name], "dueno": node.get("group"),
            "contrato": meta.get("contract_version"), "criticidad": meta.get("criticality"),
            "consumidores": sorted(e["name"] for e in exposures.values()
                                   if node["unique_id"] in ((e.get("depends_on") or {}).get("nodes") or [])),
            "certificacion_publicado": published_cert.get(name, "UNKNOWN"),
            "certificacion_reconstruccion": rebuilt.get(name, "UNKNOWN"),
            **integ[relations[name]],
        })
    classification = gov.classify(operation)
    content = {
        "version": 1,
        "generado_en": evidence.utc_now(),
        "commit": _commit(),
        "corrida": os.environ.get("GITHUB_RUN_ID", "local"),
        "operacion": operation,
        "producto": product or "todos",
        "descripcion": OPERATIONS[operation],
        "motivo": reason,
        "condicion_simulada": condition,
        "clasificacion": classification,
        "riesgo": gov.risk(classification, affected),
        "afectados": affected,
        "impacto": gov.impact(operation, affected),
        "recomendacion": gov.recommend(classification, affected),
    }
    return gov.seal(content)


def render(p: dict) -> str:
    return gov.render(p)


def request_command(p: dict) -> str | None:
    if p["operacion"] == "cambio-contrato":
        return None
    return (f'gh workflow run destructivo.yml -f operacion={p["operacion"]} -f producto={p["producto"]} '
            f'-f motivo="{p["motivo"]}"')


def save(p: dict, out_dir: Path) -> Path:
    """Guarda la propuesta sellada (JSON) y su presentación (Markdown, derivada del JSON)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "propuesta.json"
    out.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(render(p), encoding="utf-8")
    return out
