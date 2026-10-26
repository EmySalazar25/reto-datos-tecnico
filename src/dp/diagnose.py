"""Diagnóstico de la última corrida: qué falló, dónde, con qué evidencia y qué mecanismos
conocidos lo explican.

No reemplaza el razonamiento del agente: le entrega la evidencia mínima para razonar sobre el
MECANISMO de la falla (fan-out, duplicado CDC, pérdida por join...) en lugar del stack trace.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from dp import evidence


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _sample(db_path: Path, sql: str, limit: int = 5) -> dict:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cur = con.execute(f"select * from ({sql}) as t limit {limit}")
        return {"columnas": [d[0] for d in cur.description], "filas": [[str(v) for v in r] for r in cur.fetchall()]}
    except Exception as exc:
        return {"error": str(exc).splitlines()[0]}
    finally:
        con.close()


def diagnose(evidence_dir: Path, db_path: Path, catalog: list) -> list:
    manifest = evidence.load_json(evidence_dir / "manifest.json") or {}
    rr = evidence.load_json(evidence_dir / "run_results.json") or {"results": []}
    nodes = {**manifest.get("nodes", {}), **manifest.get("unit_tests", {})}
    findings = []
    for r in rr["results"]:
        if r["status"] not in ("fail", "error", "warn"):
            continue
        uid = r["unique_id"]
        node = nodes.get(uid, {})
        cfg = node.get("config") or {}
        meta = {**(node.get("meta") or {}), **(cfg.get("meta") or {})}
        item = {
            "nodo": uid,
            "tipo": node.get("resource_type"),
            "estado": r["status"],
            "archivo": node.get("original_file_path"),
            "regla": meta.get("rule"),
            "prueba_de": sorted(set(cfg.get("tags") or [])),
            "depende_de": (node.get("depends_on") or {}).get("nodes"),
            # El mensaje de un unit test trae el diff real vs esperado: se conserva completo.
            "mensaje": ANSI.sub("", str(r.get("message") or "")).strip()[:1500],
        }
        if r.get("failures") is not None:
            item["filas_que_fallan"] = r["failures"]
        if node.get("resource_type") == "test" and node.get("compiled_code"):
            item["muestra"] = _sample(db_path, node["compiled_code"])
        short = uid.split(".")[-1] if uid.startswith("unit_test.") else (uid.split(".")[2] if uid.count(".") >= 2 else uid)
        item["mecanismos_conocidos"] = [
            {"escenario": s["id"], "mecanismo": " ".join((s.get("mecanismo") or "").split())}
            for s in catalog
            if any(pat in short or pat in uid for pat in (s.get("debe_detectar") or {}).get("tests") or [])
        ]
        findings.append(item)
    return findings


def render(findings: list) -> str:
    if not findings:
        return "sin fallas en la última corrida"
    lines = [f"{len(findings)} nodos con falla o advertencia en la última corrida"]
    for f in findings:
        lines.append(f"- {f['estado'].upper()} {f['tipo']} {f['nodo']}")
        lines.append(f"  archivo: {f['archivo']} · regla: {f['regla'] or '-'} · tipo de prueba: {', '.join(f['prueba_de']) or 'técnica'}")
        if f.get("filas_que_fallan") is not None:
            lines.append(f"  filas que fallan: {f['filas_que_fallan']}")
        if f.get("mensaje"):
            msg = f["mensaje"].replace("\n", "\n    ")
            lines.append(f"  mensaje: {msg[:900]}")
        m = f.get("muestra")
        if m and "filas" in m:
            lines.append(f"  muestra: {m['columnas']} → {m['filas'][:3]}")
        for k in f.get("mecanismos_conocidos") or []:
            lines.append(f"  mecanismo conocido ({k['escenario']}): {k['mecanismo'][:220]}")
    return "\n".join(lines)
