"""Chaos: romper a propósito y verificar que el estándar lo detecta.

- `run`: cada escenario corre en un sandbox (copia del proyecto dbt, de los datos y una base
  nueva). Nunca toca el repo ni la base local. Resultado: DETECTADO o ESCAPÓ por escenario,
  con la evidencia de qué lo detectó y en qué estado quedó cada producto.
- `inject` / `restore`: aplica un escenario al repo de trabajo para la demo completa
  (falla → diagnóstico del agente → fix → recertificación).

Solo corre en entornos permitidos (DP_ENTORNO = dev | ci).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import yaml

from dp import dbt_runner, evidence, ingest, paths
from dp.sources import load_declared_sources

ALLOWED_ENVS = {"dev", "ci"}
CATALOG = paths.ROOT / "standard" / "chaos" / "catalogo.yml"
POLICY = paths.ROOT / "standard" / "policy.yml"


class ChaosError(RuntimeError):
    pass


def guard() -> str:
    env = os.environ.get("DP_ENTORNO", "dev")
    if env not in ALLOWED_ENVS:
        raise ChaosError(f"chaos bloqueado en el entorno '{env}': solo se permite en {sorted(ALLOWED_ENVS)}")
    return env


def load_catalog(path: Path = CATALOG) -> list:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("escenarios") or []


def find(catalog: list, scenario_id: str) -> dict:
    for s in catalog:
        if s["id"] == scenario_id:
            return s
    raise ChaosError(f"escenario desconocido: {scenario_id}")


# ---------------------------------------------------------------- inyección de código


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def apply_patch(text: str, buscar: str, reemplazar: str) -> str:
    """Reemplaza un bloque de líneas comparando sin indentación y conserva la del archivo."""
    file_lines = text.splitlines()
    find_lines = [l for l in buscar.strip("\n").splitlines()]
    stripped = [l.strip() for l in find_lines]
    hits = [
        i for i in range(len(file_lines) - len(stripped) + 1)
        if [l.strip() for l in file_lines[i:i + len(stripped)]] == stripped
    ]
    if len(hits) != 1:
        raise ChaosError(f"el fragmento a inyectar aparece {len(hits)} veces (se esperaba 1): el escenario está desactualizado")
    start = hits[0]
    base = _indent(file_lines[start])
    repl_lines = reemplazar.strip("\n").splitlines()
    repl_base = min((len(_indent(l)) for l in repl_lines if l.strip()), default=0)
    new_block = [base + l[repl_base:] if l.strip() else "" for l in repl_lines]
    out = file_lines[:start] + new_block + file_lines[start + len(stripped):]
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


# ---------------------------------------------------------------- inyección de datos


def inject_data(data_dir: Path, spec: dict) -> Path:
    accion = spec.get("accion")
    origen = data_dir / spec["origen"]
    destino = data_dir / spec["destino"]
    if destino.exists():
        raise ChaosError(f"la entrega {destino.name} ya existe")
    if accion == "copiar_entrega":
        shutil.copytree(origen, destino)
        return destino
    if accion == "entrega_derivada":
        with (origen / spec["archivo"]).open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            col, igual = spec["filtro"]["columna"], spec["filtro"]["igual"]
            rows = [r for r in reader if (r.get(col) or "").strip() == igual][: spec.get("max_filas", 5)]
        for r in rows:
            r.update(spec.get("cambios") or {})
            if spec.get("incremento_lsn"):
                r["_ab_cdc_lsn"] = str(int(r["_ab_cdc_lsn"]) + int(spec["incremento_lsn"]))
        destino.mkdir(parents=True)
        with (destino / spec["archivo"]).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return destino
    raise ChaosError(f"acción de datos desconocida: {accion}")


# ---------------------------------------------------------------- ejecución en sandbox


def _make_sandbox() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="dp-chaos-"))
    shutil.copytree(paths.DBT_DIR, tmp / "dbt", ignore=shutil.ignore_patterns("target", "logs", "dbt_packages"))
    shutil.copytree(paths.DATA_DIR, tmp / "data" / "replica", ignore=shutil.ignore_patterns("carga_chaos_*"))
    return tmp


def _merged_run_results(dbt_dir: Path, run_json: dict | None) -> dict:
    test_json = evidence.load_json(dbt_dir / "target" / "run_results.json") or {"results": []}
    by_id = {r["unique_id"]: r for r in (run_json or {}).get("results", [])}
    for r in test_json.get("results", []):
        by_id[r["unique_id"]] = r
    return {"metadata": test_json.get("metadata"), "results": list(by_id.values())}


def run_scenario(s: dict, keep: bool = False) -> dict:
    from dp.certify import engine

    started = time.time()
    sandbox = _make_sandbox()
    dbt_dir, data_dir, db = sandbox / "dbt", sandbox / "data" / "replica", sandbox / "chaos.duckdb"
    ev_dir = sandbox / ".evidence"
    report = {"id": s["id"], "nombre": s["nombre"], "tipo": s["tipo"], "reglas": s.get("reglas") or [],
              "mecanismo": " ".join((s.get("mecanismo") or "").split())}
    try:
        iny = s.get("inyeccion") or {}
        if s["tipo"] == "codigo":
            target = dbt_dir / iny["archivo"]
            target.write_text(apply_patch(target.read_text(encoding="utf-8"), iny["buscar"], iny["reemplazar"]), encoding="utf-8")
        elif s["tipo"] == "datos":
            inject_data(data_dir, iny)

        ingest.ingest_all(db, data_dir, load_declared_sources(dbt_dir))
        dbt_runner.run_dbt(["run"], project_dir=dbt_dir, db_path=db, quiet=True)
        run_json = evidence.load_json(dbt_dir / "target" / "run_results.json")
        dbt_runner.run_dbt(["test"], project_dir=dbt_dir, db_path=db, quiet=True)
        ev_dir.mkdir()
        shutil.copy2(dbt_dir / "target" / "manifest.json", ev_dir / "manifest.json")
        evidence.write_json(ev_dir / "run_results.json", _merged_run_results(dbt_dir, run_json))
        registry = evidence.dump_registry(db)
        evidence.write_json(ev_dir / "entregas.json", registry)
        evidence.write_json(ev_dir / "build.json", {"commit": f"chaos-{s['id']}", "codigo_salida": None, "fin": evidence.utc_now()})

        as_of = None
        if iny.get("as_of_offset_horas"):
            base_as_of, _ = engine.resolve_as_of(registry, None)
            as_of = (base_as_of + timedelta(hours=iny["as_of_offset_horas"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Un escenario de código simula un PR con un bug: se evalúa como versión candidata.
        # Los de datos y reloj simulan la operación: la versión no cambió.
        context = "candidate" if s["tipo"] == "codigo" else "run"
        report["contexto"] = context
        cert = engine.certify(ev_dir, POLICY, context=context, as_of=as_of)
        statuses = {p["product"]["id"]: p["status"] for p in cert["products"]}
        checks_nok = {c["id"] for p in cert["products"] for c in p["checks"] if c["status"] not in ("PASS", "NOT_APPLICABLE")}

        results = evidence.load_json(ev_dir / "run_results.json")["results"]
        failed = sorted(r["unique_id"] for r in results if r["status"] in ("fail", "error") and r["unique_id"].startswith(("test.", "unit_test.")))
        expected = s.get("debe_detectar") or {}
        matched_tests = [pat for pat in expected.get("tests") or [] if any(pat in uid for uid in failed)]
        tests_ok = not expected.get("tests") or bool(matched_tests)
        checks_ok = all(c in checks_nok for c in expected.get("checks") or [])
        reg = expected.get("registro")
        registro_ok = True
        if reg:
            registro_ok = any(r["id_entrega"] == reg["entrega"] and r["estado"] == reg["estado"] for r in registry)
        estados_ok = all(statuses.get(p) == st for p, st in (s.get("estado_esperado") or {}).items())

        report.update({
            "estado": "DETECTADO" if (tests_ok and checks_ok and registro_ok and estados_ok) else "ESCAPÓ",
            "detectado_por": {"tests": matched_tests, "checks": [c for c in expected.get("checks") or [] if c in checks_nok],
                              "registro": reg if (reg and registro_ok) else None},
            "estado_esperado": s.get("estado_esperado") or {},
            "estado_obtenido": statuses,
            "tests_que_fallaron": len(failed),
            "muestra_tests_que_fallaron": [u.split(".")[-1] if u.startswith("unit_test.") else u.split(".")[2] for u in failed[:8]],
        })
    except ChaosError as exc:
        report.update({"estado": "ERROR", "error": str(exc)})
    finally:
        report["duracion_s"] = round(time.time() - started, 1)
        if not keep:
            shutil.rmtree(sandbox, ignore_errors=True)
        else:
            report["sandbox"] = str(sandbox)
    return report


def control(scenario: dict) -> dict:
    """En la implementación correcta, los tests que deben detectar el escenario pasan."""
    rr = evidence.load_json(paths.EVIDENCE_DIR / "run_results.json")
    if rr is None:
        return {"estado": "sin evidencia de la corrida principal"}
    by_id = {r["unique_id"]: r["status"] for r in rr["results"]}
    out = {}
    for pat in (scenario.get("debe_detectar") or {}).get("tests") or []:
        found = [st for uid, st in by_id.items() if pat in uid]
        out[pat] = "PASS" if found and all(st == "pass" for st in found) else ("NO_ENCONTRADO" if not found else "FALLA")
    return out


def run_all(ids=None, keep: bool = False) -> dict:
    env = guard()
    catalog = load_catalog()
    selected = [s for s in catalog if not ids or s["id"] in ids]
    escenarios = []
    for s in selected:
        r = run_scenario(s, keep=keep)
        r["control_implementacion_correcta"] = control(s)
        escenarios.append(r)
    # Una corrida parcial actualiza sus escenarios y conserva los demás resultados.
    previous = evidence.load_json(paths.EVIDENCE_DIR / "chaos_resultados.json") or {}
    merged = {e["id"]: e for e in previous.get("escenarios") or [] if e["id"] in {s["id"] for s in catalog}}
    merged.update({e["id"]: e for e in escenarios})
    payload = {"generated_at": evidence.utc_now(), "entorno": env,
               "escenarios": [merged[s["id"]] for s in catalog if s["id"] in merged]}
    evidence.write_json(paths.EVIDENCE_DIR / "chaos_resultados.json", payload)
    return {**payload, "escenarios": escenarios}


# ---------------------------------------------------------------- demo en el repo de trabajo


def _git_clean(path: Path) -> bool:
    return subprocess.call(["git", "diff", "--quiet", "--", str(path)], cwd=paths.ROOT) == 0


def inject(scenario_id: str) -> str:
    guard()
    s = find(load_catalog(), scenario_id)
    iny = s.get("inyeccion") or {}
    if s["tipo"] == "codigo":
        target = paths.DBT_DIR / iny["archivo"]
        if not _git_clean(target):
            raise ChaosError(f"{target.relative_to(paths.ROOT)} tiene cambios sin commit; no se inyecta sobre trabajo en curso")
        target.write_text(apply_patch(target.read_text(encoding="utf-8"), iny["buscar"], iny["reemplazar"]), encoding="utf-8")
        return f"inyectado en {target.relative_to(paths.ROOT)}. Corre `make all certify` para ver el efecto."
    if s["tipo"] == "datos":
        dest = inject_data(paths.DATA_DIR, iny)
        return f"entrega {dest.name} creada. Corre `make all certify` para ver el efecto."
    hours = iny.get("as_of_offset_horas")
    return f"escenario de reloj: corre `dp certify run --as-of <última extracción + {hours} h>`"


def restore(scenario_id: str) -> str:
    guard()
    s = find(load_catalog(), scenario_id)
    iny = s.get("inyeccion") or {}
    if s["tipo"] == "codigo":
        target = paths.DBT_DIR / iny["archivo"]
        target.write_text(apply_patch(target.read_text(encoding="utf-8"), iny["reemplazar"], iny["buscar"]), encoding="utf-8")
        return f"restaurado {target.relative_to(paths.ROOT)}"
    if s["tipo"] == "datos":
        dest = paths.DATA_DIR / iny["destino"]
        shutil.rmtree(dest, ignore_errors=True)
        # landing es de solo agregar: quitar una entrega exige reconstruir la base local.
        paths.DUCKDB_PATH.unlink(missing_ok=True)
        return f"entrega {dest.name} eliminada y base local borrada. Corre `make all certify` para reconstruir."
    return "escenario de reloj: no hay nada que restaurar"


def summary_lines(payload: dict) -> list:
    lines = []
    for e in payload["escenarios"]:
        por = e.get("detectado_por") or {}
        quien = ", ".join((por.get("tests") or []) + (por.get("checks") or []) + (["registro de entregas"] if por.get("registro") else []))
        lines.append(f"{e['id']} {e['nombre']:<38} {e['estado']:<10} {quien or e.get('error', '-')}")
        if e.get("estado_obtenido"):
            lines.append(f"      certificación: {json.dumps(e['estado_obtenido'], ensure_ascii=False)} ({e['duracion_s']} s)")
    det = sum(e["estado"] == "DETECTADO" for e in payload["escenarios"])
    lines.append(f"resumen: {det}/{len(payload['escenarios'])} escenarios DETECTADOS")
    return lines
