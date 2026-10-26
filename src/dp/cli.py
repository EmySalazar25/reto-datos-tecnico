"""Punto de entrada `dp`. Cada subcomando devuelve una salida corta, útil para personas y para el agente."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dp import dbt_runner, evidence, idempotency, ingest, paths
from dp.sources import load_declared_sources

CERT_DIR = paths.ROOT / ".certification"
POLICY = paths.ROOT / "standard" / "policy.yml"


def cmd_ingest(args: argparse.Namespace) -> int:
    declared = load_declared_sources(paths.DBT_DIR)
    results = ingest.ingest_all(paths.DUCKDB_PATH, paths.DATA_DIR, declared, only=args.entrega)
    if not results:
        print(f"sin entregas en {paths.DATA_DIR}")
        return 0
    for r in results:
        print(r.line())
    cargadas = sum(r.estado == "cargada" for r in results)
    rechazadas = [r for r in results if r.estado == "rechazada"]
    print(f"resumen: {cargadas} cargadas · {len(rechazadas)} rechazadas · {len(results)} archivos revisados")
    return 1 if rechazadas else 0


def run_build(select=None) -> int:
    started = evidence.utc_now()
    dbt_args = ["build"]
    if select:
        dbt_args += ["--select", select]
    code = dbt_runner.run_dbt(dbt_args)
    # La evidencia se guarda aunque el build falle: una falla también es evidencia.
    evidence.snapshot_build(paths.EVIDENCE_DIR, paths.DBT_DIR, paths.DUCKDB_PATH, paths.ROOT, code, started)
    return code


def cmd_build(args: argparse.Namespace) -> int:
    return run_build(args.select)


def cmd_verify_idempotency(args: argparse.Namespace) -> int:
    declared = load_declared_sources(paths.DBT_DIR)
    ingest.ingest_all(paths.DUCKDB_PATH, paths.DATA_DIR, declared)
    if run_build() != 0:
        print("la primera corrida falló: corrige el build antes de verificar idempotencia")
        return 1
    first = idempotency.table_fingerprints(paths.DUCKDB_PATH)
    ingest.ingest_all(paths.DUCKDB_PATH, paths.DATA_DIR, declared)
    run_build()
    second = idempotency.table_fingerprints(paths.DUCKDB_PATH)
    report = idempotency.compare(first, second)
    report["generated_at"] = evidence.utc_now()
    evidence.write_json(paths.EVIDENCE_DIR / "idempotencia.json", report)
    print(f"idempotencia: {report['status']} · {len(report['tablas'])} tablas comparadas")
    for t in report["tablas_con_cambios"]:
        print(f"  cambió: {t}")
    return 0 if report["status"] == "PASS" else 1


def cmd_certify_run(args: argparse.Namespace) -> int:
    from dp.certify import engine, render

    result = engine.certify(
        paths.EVIDENCE_DIR,
        POLICY,
        context=args.context,
        as_of=args.as_of,
        base_manifest=Path(args.base_manifest) if args.base_manifest else None,
        base_policy=Path(args.base_policy) if args.base_policy else None,
        approved_by=args.aprobado_por,
    )
    out = Path(args.salida) if args.salida else CERT_DIR
    render.write_outputs(result, out)
    summary = (out / "resumen.md").read_text(encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary)
    for p in result["products"]:
        print(f"{p['product']['id']:<24} {p['status']:<24} salud {p['health']:<9} razones: {', '.join(p['reasons']) or '-'}")
    print(f"detalle: {out}/<producto>.json · resumen: {out}/resumen.md")
    return 1 if any(p["status"] == "NOT_CERTIFIED" for p in result["products"]) else 0


def _load_cert(product: str) -> dict:
    path = CERT_DIR / f"{product}.json"
    if not path.exists():
        raise SystemExit(f"no hay certificación de {product}: corre `dp certify run`")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_certify_status(args: argparse.Namespace) -> int:
    from dp.certify import render

    if args.producto:
        print(render.agent_status(_load_cert(args.producto)))
        return 0
    catalog = CERT_DIR / "catalogo.json"
    if not catalog.exists():
        print("no hay certificaciones: corre `dp certify run`")
        return 1
    data = json.loads(catalog.read_text(encoding="utf-8"))
    for p in data["products"]:
        print(f"{p['product']:<24} {p['status']:<24} salud {p['health']:<9} razones: {', '.join(p['reasons']) or '-'}")
    return 0


def _failing_rows(compiled_sql: str, limit: int = 5) -> dict:
    import duckdb

    con = duckdb.connect(str(paths.DUCKDB_PATH), read_only=True)
    try:
        cur = con.execute(f"select * from ({compiled_sql}) as t limit {limit}")
        cols = [d[0] for d in cur.description]
        return {"columnas": cols, "filas": [[str(v) for v in row] for row in cur.fetchall()]}
    except Exception as exc:  # la evidencia no debe romper la explicación
        return {"error": str(exc).splitlines()[0]}
    finally:
        con.close()


def cmd_certify_explain(args: argparse.Namespace) -> int:
    prod = _load_cert(args.producto)
    check = next((c for c in prod["checks"] if c["id"] == args.check), None)
    if check is None:
        print(f"{args.check} no existe en la certificación de {args.producto}")
        return 1
    manifest = evidence.load_json(paths.EVIDENCE_DIR / "manifest.json") or {}
    nodes = {**manifest.get("nodes", {}), **manifest.get("unit_tests", {})}
    detail = dict(check)
    enriched = []
    for item in check.get("evidence", []):
        item = dict(item)
        node = nodes.get(item.get("ref", ""))
        if node:
            item["archivo"] = node.get("original_file_path")
            if node.get("resource_type") == "test" and node.get("compiled_code"):
                item["muestra_filas_que_fallan"] = _failing_rows(node["compiled_code"])
        enriched.append(item)
    detail["evidence"] = enriched
    print(json.dumps(detail, ensure_ascii=False, indent=2))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    from dp import profile

    declared = load_declared_sources(paths.DBT_DIR)
    try:
        result = profile.profile(paths.DUCKDB_PATH, args.tabla, declared)
    except ValueError as exc:
        print(f"profile: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str) if args.json else profile.render(result))
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    from dp import chaos, diagnose

    findings = diagnose.diagnose(paths.EVIDENCE_DIR, paths.DUCKDB_PATH, chaos.load_catalog())
    print(json.dumps(findings, ensure_ascii=False, indent=2) if args.json else diagnose.render(findings))
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    from dp import propose

    try:
        p = propose.plan(args.operacion, args.producto, args.motivo, paths.EVIDENCE_DIR, CERT_DIR, paths.DUCKDB_PATH)
    except ValueError as exc:
        print(f"propose: {exc}")
        return 1
    path = propose.save(p, paths.EVIDENCE_DIR)
    print(propose.render(p))
    print(f"propuesta guardada en {path.relative_to(paths.ROOT)}")
    return 0


def cmd_new_source(args: argparse.Namespace) -> int:
    from dp import scaffold

    try:
        written = scaffold.new_source(paths.DBT_DIR, paths.DATA_DIR, args.tabla, args.entrega, args.sistema,
                                     args.llave.split(",") if args.llave else None)
    except ValueError as exc:
        print(f"new-source: {exc}")
        return 1
    for w in written:
        print(f"escrito: {w.relative_to(paths.ROOT)}")
    print("siguiente: confirma la llave con `dp ingest` + `dp profile " + args.tabla + "`, completa los PENDIENTE y corre `dp build`")
    return 0


AGENT_PROMPT = (
    "Los productos de datos perdieron su certificación después de un cambio en el código. "
    "Usa la skill diagnosticar-falla: revisa `dp certify status` y `dp diagnose`, explica el mecanismo "
    "con el formato de la skill y corrige la causa en el código, sin bajar la vara. Después corre "
    "`dp build` y `dp certify run --context candidate` y confirma que todo vuelve a CERTIFIED. No hagas push."
)


def _certify_quiet(context: str = "run") -> dict:
    from dp.certify import engine, render

    result = engine.certify(paths.EVIDENCE_DIR, POLICY, context=context)
    render.write_outputs(result, CERT_DIR)
    return {p["product"]["id"]: p["status"] for p in result["products"]}


def chaos_demo(scenario_id: str) -> int:
    import shutil
    import subprocess

    from dp import chaos

    def step(title: str) -> None:
        print(f"\n=== {title}")

    step("1. Estado inicial")
    run_build()
    before = _certify_quiet()
    print(before)

    step(f"2. Se rompe algo a propósito ({scenario_id})")
    print(chaos.inject(scenario_id))
    run_build()
    broken = _certify_quiet("candidate")
    print(broken)

    step("3. El estándar lo detecta y lo explica")
    for prod, st in broken.items():
        if st != "CERTIFIED":
            print(render_status(prod))
    cmd_diagnose(argparse.Namespace(json=False))

    step("4. Corrección")
    agent = shutil.which("opencode")
    if agent and os.environ.get("DP_AGENTE", "1") != "0":
        print(f"el agente diagnostica y corrige (opencode run):\n{AGENT_PROMPT}\n")
        subprocess.call([agent, "run", AGENT_PROMPT], cwd=paths.ROOT)
    else:
        print("opencode no está instalado (o DP_AGENTE=0): se restaura de forma determinista.")
        print(f"Para verlo con el agente: instala opencode y pídele:\n  {AGENT_PROMPT}")
        print(chaos.restore(scenario_id))

    step("5. Recertificación")
    run_build()
    after = _certify_quiet("candidate")
    print(after)
    recovered = all(st == "CERTIFIED" for st in after.values())
    print(f"\nresultado: {before} → {broken} → {after}")
    print("RECUPERADO" if recovered else "NO RECUPERADO: revisa `dp certify status`")
    return 0 if recovered else 1


def render_status(product: str) -> str:
    from dp.certify import render

    return render.agent_status(_load_cert(product))


def cmd_chaos(args: argparse.Namespace) -> int:
    from dp import chaos

    try:
        if args.accion == "demo":
            return chaos_demo(args.escenario_id)
        if args.accion == "run":
            payload = chaos.run_all(ids=args.escenario or None, keep=args.conservar)
            for line in chaos.summary_lines(payload):
                print(line)
            return 0 if all(e["estado"] == "DETECTADO" for e in payload["escenarios"]) else 1
        if args.accion == "list":
            for s in chaos.load_catalog():
                print(f"{s['id']} {s['tipo']:<7} {s['nombre']:<38} reglas {s.get('reglas') or '-'}")
            return 0
        if args.accion == "inject":
            print(chaos.inject(args.escenario_id))
            return 0
        if args.accion == "restore":
            print(chaos.restore(args.escenario_id))
            return 0
    except chaos.ChaosError as exc:
        print(f"chaos: {exc}")
        return 2
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dp", description="Estándar de ingeniería de datos.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingiere las entregas nuevas a landing (idempotente)")
    p_ingest.add_argument("--entrega", help="solo esta entrega (p. ej. carga_2)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_build = sub.add_parser("build", help="dbt build (modelos, tests y contratos) + snapshot de evidencia")
    p_build.add_argument("--select", help="selector de dbt")
    p_build.set_defaults(func=cmd_build)

    p_idem = sub.add_parser("verify-idempotency", help="corre todo dos veces y compara filas y contenido")
    p_idem.set_defaults(func=cmd_verify_idempotency)

    p_prof = sub.add_parser("profile", help="perfil compacto de una tabla (CDC, nulos, variantes, centinelas, tipos)")
    p_prof.add_argument("tabla", help="fle_viaje, staging.stg_fle__viajes, embarques_mensual…")
    p_prof.add_argument("--json", action="store_true")
    p_prof.set_defaults(func=cmd_profile)

    p_prop = sub.add_parser("propose", help="propone una operación destructiva con su impacto (no la ejecuta)")
    p_prop.add_argument("operacion", choices=["full-refresh", "recrear-producto", "cambio-contrato"])
    p_prop.add_argument("--producto")
    p_prop.add_argument("--motivo", required=True)
    p_prop.set_defaults(func=cmd_propose)

    p_new = sub.add_parser("new-source", help="esqueleto estándar (fuente + staging + tests) para una tabla nueva")
    p_new.add_argument("tabla", help="nombre del CSV sin extensión, p. ej. mto_equipo")
    p_new.add_argument("--entrega", required=True, help="carpeta de la entrega en data/replica/")
    p_new.add_argument("--sistema", help="prefijo del sistema (por omisión, el prefijo de la tabla)")
    p_new.add_argument("--llave", help="llave primaria, separada por comas (por omisión, la primera columna)")
    p_new.set_defaults(func=cmd_new_source)

    p_diag = sub.add_parser("diagnose", help="qué falló en la última corrida, con evidencia y mecanismos conocidos")
    p_diag.add_argument("--json", action="store_true")
    p_diag.set_defaults(func=cmd_diagnose)

    p_cert = sub.add_parser("certify", help="certificación de productos de datos")
    cert_sub = p_cert.add_subparsers(dest="accion", required=True)

    p_run = cert_sub.add_parser("run", help="evalúa la evidencia contra la política")
    p_run.add_argument("--context", default="run", choices=["run", "candidate", "ci"])
    p_run.add_argument("--as-of", help="instante de evaluación (ISO UTC); por omisión, reloj replay")
    p_run.add_argument("--base-manifest", help="manifest de la versión base (CI) para GOV-07")
    p_run.add_argument("--base-policy", help="policy.yml de la versión base (CI) para GOV-07")
    p_run.add_argument("--aprobado-por", help="aprobador humano registrado por el environment de CI")
    p_run.add_argument("--salida", help="directorio de salida (por omisión .certification/)")
    p_run.set_defaults(func=cmd_certify_run)

    p_status = cert_sub.add_parser("status", help="resumen compacto (para personas y agente)")
    p_status.add_argument("producto", nargs="?")
    p_status.set_defaults(func=cmd_certify_status)

    p_explain = cert_sub.add_parser("explain", help="evidencia completa de un check")
    p_explain.add_argument("producto")
    p_explain.add_argument("check")
    p_explain.set_defaults(func=cmd_certify_explain)

    p_chaos = sub.add_parser("chaos", help="rompe a propósito y verifica que el estándar lo detecta")
    chaos_sub = p_chaos.add_subparsers(dest="accion", required=True)
    p_crun = chaos_sub.add_parser("run", help="ejecuta escenarios en un sandbox aislado")
    p_crun.add_argument("escenario", nargs="*", help="IDs (por omisión, todos)")
    p_crun.add_argument("--conservar", action="store_true", help="no borrar el sandbox (para depurar)")
    p_crun.set_defaults(func=cmd_chaos)
    p_clist = chaos_sub.add_parser("list", help="lista el catálogo")
    p_clist.set_defaults(func=cmd_chaos)
    p_cinj = chaos_sub.add_parser("inject", help="aplica un escenario al repo de trabajo (demo)")
    p_cinj.add_argument("escenario_id")
    p_cinj.set_defaults(func=cmd_chaos)
    p_cres = chaos_sub.add_parser("restore", help="revierte un escenario inyectado")
    p_cres.add_argument("escenario_id")
    p_cres.set_defaults(func=cmd_chaos)
    p_cdemo = chaos_sub.add_parser("demo", help="certificado → falla → detección → corrección → recertificación")
    p_cdemo.add_argument("escenario_id", nargs="?", default="CH-01")
    p_cdemo.set_defaults(func=cmd_chaos)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
