"""Registro de checks del estándar.

Cada check es una función determinista que recibe el contexto de evaluación y un producto y
devuelve un resultado con su evidencia. Ningún check consulta nada fuera de la evidencia.
Estados: PASS · WARN · FAIL · UNKNOWN (evidencia requerida ausente) · NOT_APPLICABLE.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from dp.certify.graph import FAIL_STATUSES, PASS_STATUSES, Graph, Product


@dataclass
class Ctx:
    graph: Graph
    results: dict  # unique_id -> resultado de run_results
    registry: list  # filas de ops.entregas
    context: str  # run | ci
    as_of: datetime
    policy: dict
    idempotencia: dict | None = None
    chaos: dict | None = None
    base_graph: Graph | None = None
    policy_changed: bool | None = None
    approved_by: str | None = None


@dataclass
class CheckResult:
    id: str
    dimension: str
    title: str
    phase: str
    status: str
    summary: str
    evidence: list = field(default_factory=list)
    counts: dict | None = None
    rule: str | None = None
    owner: str | None = None
    severity: str = "error"
    recovery: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


REGISTRY: dict = {}


def check(check_id: str, dimension: str, title: str, phase: str, recovery: str):
    """phase: design | runtime | data (data = design en CI, runtime en operación)."""

    def wrap(fn: Callable):
        REGISTRY[check_id] = {"fn": fn, "dimension": dimension, "title": title, "phase": phase, "recovery": recovery}
        return fn

    return wrap


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    s = str(value).replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _status_of(ctx: Ctx, unique_id: str) -> str:
    r = ctx.results.get(unique_id)
    if r is None:
        return "UNKNOWN"
    s = r.get("status")
    if s in PASS_STATUSES:
        return "PASS"
    if s == "warn":
        return "WARN"
    if s in FAIL_STATUSES:
        return "FAIL"
    return "UNKNOWN"  # skipped u otro: no hay evidencia de que haya pasado


def _evaluate_tests(ctx: Ctx, tests: list, label: str) -> tuple:
    if not tests:
        return "FAIL", f"no hay tests {label}", [], {"pasan": 0, "total": 0}
    evidence, statuses = [], []
    for t in tests:
        st = _status_of(ctx, t.unique_id)
        statuses.append(st)
        if st != "PASS":
            r = ctx.results.get(t.unique_id) or {}
            item = {"tipo": "dbt_test", "ref": t.unique_id, "estado": st}
            if r.get("failures") is not None:
                item["filas_que_fallan"] = r.get("failures")
            if r.get("message"):
                item["mensaje"] = str(r["message"]).strip().splitlines()[0][:300]
            if t.rule:
                item["regla"] = t.rule
            evidence.append(item)
    total, ok = len(statuses), statuses.count("PASS")
    counts = {"pasan": ok, "total": total}
    if "FAIL" in statuses:
        return "FAIL", f"{total - ok} de {total} tests {label} no pasan", evidence, counts
    if "UNKNOWN" in statuses:
        return "UNKNOWN", f"{statuses.count('UNKNOWN')} tests {label} sin resultado en la última corrida", evidence, counts
    if "WARN" in statuses:
        return "WARN", f"{statuses.count('WARN')} tests {label} en advertencia", evidence, counts
    return "PASS", f"{ok}/{total} tests {label} pasan", evidence, counts


def _tests_of_kind(ctx: Ctx, p: Product, kind: str) -> list:
    return [t for t in ctx.graph.tests_for(p) if t.kind == kind]


def _grain_test(ctx: Ctx, p: Product):
    grain = list(p.meta.get("grain") or [])
    for t in ctx.graph.tests_for(p):
        if t.generic_name == "combinacion_unica" and t.attached_node == p.unique_id:
            cols = list(t.kwargs.get("columnas") or [])
            if sorted(cols) == sorted(grain):
                return t
    return None


# ---------------------------------------------------------------- Testing


@check("TST-01", "testing", "Tests técnicos", "data", "Corrige el modelo o los datos que rompen el test; revisa `dp certify explain`.")
def tst_01(ctx, p):
    return _evaluate_tests(ctx, _tests_of_kind(ctx, p, "technical"), "técnicos")


@check("TST-02", "testing", "Contrato de esquema", "design", "Alinea columnas y tipos del modelo con su contrato, o propone un cambio de contrato aprobado.")
def tst_02(ctx, p):
    enforced = ((p.node.get("config") or {}).get("contract") or {}).get("enforced")
    if not enforced:
        return "FAIL", "el producto no tiene contrato aplicado", [], None
    st = _status_of(ctx, p.unique_id)
    r = ctx.results.get(p.unique_id) or {}
    ev = [] if st == "PASS" else [{"tipo": "dbt_model", "ref": p.unique_id, "estado": st, "mensaje": str(r.get("message") or "")[:300]}]
    return st, ("el modelo se construyó cumpliendo su contrato" if st == "PASS" else "el modelo no se construyó con su contrato"), ev, None


@check("TST-03", "testing", "Grano protegido", "data", "Hay filas repetidas en el grano declarado: busca el join que multiplica filas.")
def tst_03(ctx, p):
    t = _grain_test(ctx, p)
    if t is None:
        return "FAIL", "el grano declarado no tiene test de unicidad", [], None
    st, summary, ev, _ = _evaluate_tests(ctx, [t], "de grano")
    return st, f"grano {p.meta.get('grain')}: " + summary, ev, None


@check("TST-04", "testing", "Tests de ingeniería", "data", "Revisa el mecanismo (CDC, fan-out, cobertura, centinelas, normalización) que señala el test.")
def tst_04(ctx, p):
    return _evaluate_tests(ctx, _tests_of_kind(ctx, p, "engineering"), "de ingeniería")


@check("TST-05", "testing", "Reglas de negocio sobre datos", "data", "La regla de negocio no se cumple: compara lo publicado contra el recálculo del test.")
def tst_05(ctx, p):
    return _evaluate_tests(ctx, _tests_of_kind(ctx, p, "business"), "de negocio")


@check("TST-06", "testing", "Reglas de negocio sobre lógica (unit tests)", "design", "La lógica no implementa la regla: el unit test muestra el caso que falla.")
def tst_06(ctx, p):
    return _evaluate_tests(ctx, _tests_of_kind(ctx, p, "unit"), "unitarios")


@check("TST-08", "testing", "Idempotencia", "design", "Correr dos veces cambió tablas: revisa deduplicación e ingesta (`dp verify-idempotency`).")
def tst_08(ctx, p):
    if ctx.idempotencia is None:
        return "UNKNOWN", "no hay evidencia de idempotencia (corre `dp verify-idempotency`)", [], None
    st = ctx.idempotencia.get("status", "UNKNOWN")
    cambios = ctx.idempotencia.get("tablas_con_cambios") or []
    ev = [{"tipo": "idempotencia", "tablas_con_cambios": cambios}] if cambios else []
    n = len(ctx.idempotencia.get("tablas") or [])
    return st, (f"{n} tablas idénticas tras dos corridas" if st == "PASS" else f"{len(cambios)} tablas cambiaron"), ev, None


@check("TST-09", "testing", "Los tests pueden fallar (chaos)", "design", "Agrega un escenario de chaos que rompa la regla y verifica que se detecte.")
def tst_09(ctx, p):
    if ctx.chaos is None:
        return "UNKNOWN", "no hay resultados de chaos (corre `dp chaos run`)", [], None
    rules = [r.get("id") for r in p.meta.get("business_rules") or []]
    escenarios = ctx.chaos.get("escenarios") or []
    covered, escaped = set(), []
    for e in escenarios:
        for rule in e.get("reglas") or []:
            if rule in rules:
                if e.get("estado") == "DETECTADO":
                    covered.add(rule)
                elif e.get("estado") == "ESCAPÓ":
                    escaped.append({"escenario": e.get("id"), "regla": rule})
    missing = [r for r in rules if r not in covered]
    ev = [{"tipo": "chaos", "reglas_sin_escenario_detectado": missing}] if missing else []
    ev += [{"tipo": "chaos", "escapo": x} for x in escaped]
    counts = {"cubiertas": len(covered), "total": len(rules)}
    if escaped or missing:
        return "FAIL", f"{len(covered)}/{len(rules)} reglas con chaos detectado", ev, counts
    return "PASS", f"{len(covered)}/{len(rules)} reglas demostraron que su test puede fallar", ev, counts


# ---------------------------------------------------------------- Gobernanza


@check("GOV-01", "governance", "Dueño", "design", "Asigna el producto a un `group` con owner y declara `meta.technical_owner`.")
def gov_01(ctx, p):
    missing = []
    if not p.owner:
        missing.append("group con owner")
    if not p.meta.get("technical_owner"):
        missing.append("meta.technical_owner")
    if missing:
        return "FAIL", "falta " + ", ".join(missing), [{"tipo": "metadata", "faltantes": missing}], None
    return "PASS", f"dueño {p.owner} · técnico {p.meta.get('technical_owner')}", [], None


@check("GOV-02", "governance", "Contrato publicado", "design", "Declara access: public, contract.enforced, data_type en cada columna y meta.contract_version.")
def gov_02(ctx, p):
    problems = []
    if p.node.get("access") != "public":
        problems.append("access no es public")
    if not ((p.node.get("config") or {}).get("contract") or {}).get("enforced"):
        problems.append("contrato no aplicado")
    sin_tipo = [c for c, v in (p.node.get("columns") or {}).items() if not v.get("data_type")]
    if sin_tipo:
        problems.append(f"columnas sin tipo: {sin_tipo}")
    cv = p.meta.get("contract_version")
    if not isinstance(cv, int) or cv < 1:
        problems.append("meta.contract_version ausente")
    if problems:
        return "FAIL", "; ".join(problems), [{"tipo": "metadata", "problemas": problems}], None
    return "PASS", f"contrato v{cv} aplicado con {len(p.node.get('columns') or {})} columnas tipadas", [], None


@check("GOV-03", "governance", "Grano y llaves declarados y protegidos", "design", "Declara meta.grain y meta.primary_key y un test combinacion_unica sobre el grano.")
def gov_03(ctx, p):
    problems = []
    if not p.meta.get("grain"):
        problems.append("meta.grain ausente")
    if not p.meta.get("primary_key"):
        problems.append("meta.primary_key ausente")
    if p.meta.get("grain") and _grain_test(ctx, p) is None:
        problems.append("el grano declarado no tiene test (una declaración sin enforcement no cuenta)")
    if problems:
        return "FAIL", "; ".join(problems), [{"tipo": "metadata", "problemas": problems}], None
    return "PASS", f"grano {p.meta['grain']} protegido por test", [], None


@check("GOV-04", "governance", "Documentación", "design", "Describe el modelo y cada columna publicada.")
def gov_04(ctx, p):
    sin_desc = [c for c, v in (p.node.get("columns") or {}).items() if not (v.get("description") or "").strip()]
    problems = []
    if not (p.node.get("description") or "").strip():
        problems.append("modelo sin descripción")
    if sin_desc:
        problems.append(f"columnas sin descripción: {sin_desc}")
    if problems:
        return "FAIL", "; ".join(problems), [{"tipo": "metadata", "problemas": problems}], None
    return "PASS", f"modelo y {len(p.node.get('columns') or {})} columnas documentadas", [], None


@check("GOV-05", "governance", "Reglas de negocio ↔ tests", "design", "Cada regla necesita un test de datos y un unit test con meta.rule; todo test de negocio debe apuntar a una regla declarada.")
def gov_05(ctx, p):
    rules = [r.get("id") for r in p.meta.get("business_rules") or []]
    if not rules:
        return "FAIL", "el producto no declara reglas de negocio", [], None
    tests = ctx.graph.tests_for(p)
    data_rules = {t.rule for t in tests if t.rule and t.kind != "unit"}
    unit_rules = {t.rule for t in tests if t.rule and t.kind == "unit"}
    sin_datos = [r for r in rules if r not in data_rules]
    sin_unit = [r for r in rules if r not in unit_rules]
    all_rules = {r.get("id") for prod in ctx.graph.products() for r in prod.meta.get("business_rules") or []}
    huerfanos = sorted({t.unique_id for t in ctx.graph.tests if t.kind == "business" and t.rule not in all_rules})
    ev = []
    if sin_datos:
        ev.append({"tipo": "reglas", "sin_test_de_datos": sin_datos})
    if sin_unit:
        ev.append({"tipo": "reglas", "sin_unit_test": sin_unit})
    if huerfanos:
        ev.append({"tipo": "reglas", "tests_de_negocio_sin_regla": huerfanos})
    counts = {"reglas": len(rules), "con_test_de_datos": len(rules) - len(sin_datos), "con_unit_test": len(rules) - len(sin_unit)}
    if ev:
        return "FAIL", "hay reglas sin test o tests sin regla", ev, counts
    return "PASS", f"{len(rules)} reglas, cada una con test de datos y unit test", [], counts


@check("GOV-06", "governance", "Linaje y consumidores", "design", "Declara una exposure para cada consumidor del producto.")
def gov_06(ctx, p):
    sources = sorted(u for u in p.closure if u.startswith("source."))
    exposures = ctx.graph.exposures_for(p)
    if not sources:
        return "FAIL", "el producto no llega a ninguna fuente declarada", [], None
    if not exposures:
        return "FAIL", "sin consumidores declarados (exposures)", [], None
    return "PASS", f"{len(sources)} fuentes → producto → {len(exposures)} consumidor(es)", [], None


def _contract_columns(node: dict) -> dict:
    return {c: (v.get("data_type") or "").lower() for c, v in (node.get("columns") or {}).items()}


@check("GOV-07", "governance", "Cambio controlado", "design", "Cambios que rompen el contrato o debilitan el estándar requieren aprobación humana en el environment.")
def gov_07(ctx, p):
    if ctx.base_graph is None:
        return "UNKNOWN", "sin versión base para comparar (se evalúa en CI contra la rama destino)", [], None
    findings = []
    base_node = ctx.base_graph.nodes.get(p.unique_id)
    if base_node is not None:
        before, after = _contract_columns(base_node), _contract_columns(p.node)
        removed = sorted(set(before) - set(after))
        retyped = sorted(c for c in before if c in after and before[c] != after[c])
        if removed or retyped:
            bumped = (p.meta.get("contract_version") or 0) > ((base_node.get("meta") or {}).get("contract_version") or 0)
            findings.append({
                "tipo": "contrato_incompatible", "columnas_eliminadas": removed, "tipos_cambiados": retyped,
                "contract_version_subio": bumped,
            })
        base_rules = {r.get("id") for r in (base_node.get("meta") or {}).get("business_rules") or []}
        now_rules = {r.get("id") for r in p.meta.get("business_rules") or []}
        if base_rules - now_rules:
            findings.append({"tipo": "reglas_eliminadas", "reglas": sorted(base_rules - now_rules)})
        base_p = next((bp for bp in ctx.base_graph.products() if bp.unique_id == p.unique_id), None)
        if base_p is not None:
            now_tests = {t.unique_id: t for t in ctx.graph.tests_for(p)}
            for t in ctx.base_graph.tests_for(base_p):
                if t.kind not in ("business", "engineering", "unit") and t.generic_name != "combinacion_unica":
                    continue
                if t.unique_id not in now_tests:
                    findings.append({"tipo": "test_eliminado", "ref": t.unique_id, "regla": t.rule})
                elif t.severity == "error" and now_tests[t.unique_id].severity == "warn":
                    findings.append({"tipo": "severidad_rebajada", "ref": t.unique_id, "regla": t.rule})
    if ctx.policy_changed:
        findings.append({"tipo": "politica_modificada", "archivo": "standard/policy.yml"})
    if not findings:
        return "PASS", "sin cambios incompatibles ni debilitamiento del estándar", [], None
    if ctx.approved_by:
        return "PASS", f"cambios gobernados aprobados por {ctx.approved_by}", findings + [{"tipo": "aprobacion", "por": ctx.approved_by}], None
    return "FAIL", f"{len(findings)} cambio(s) requieren aprobación humana", findings, None


# ---------------------------------------------------------------- Observabilidad


def _source_fqn(ctx: Ctx, source_uid: str) -> str:
    s = ctx.graph.sources[source_uid]
    return f"{s['schema']}.{s['name']}"


def _loaded(ctx: Ctx, fqn: str) -> list:
    return [r for r in ctx.registry if r.get("tabla_destino") == fqn and r.get("estado") == "cargada"]


def _hours(td) -> float:
    return round(td.total_seconds() / 3600, 1)


def _period_hours(spec: dict | None) -> float | None:
    if not spec or spec.get("count") is None:
        return None
    mult = {"minute": 1 / 60, "hour": 1, "day": 24}.get(spec.get("period"), 1)
    return spec["count"] * mult


@check("OBS-01", "observability", "Frescura de la réplica", "runtime", "La réplica no ha entregado datos recientes: revisa la sincronización antes de tocar el modelo.")
def obs_01(ctx, p):
    """STALE solo si la réplica completa dejó de entregar. En CDC, una tabla sin cambios puede no
    venir en una entrega: una fuente individual atrasada es una advertencia, no una falla."""
    sources = sorted(u for u in p.closure if u.startswith("source."))
    lags, ev, err_limits = {}, [], []
    for uid in sources:
        fresh = ctx.graph.sources[uid].get("freshness") or {}
        warn_h, err_h = _period_hours(fresh.get("warn_after")), _period_hours(fresh.get("error_after"))
        if err_h is not None:
            err_limits.append(err_h)
        fqn = _source_fqn(ctx, uid)
        extracted = [t for t in (_parse_ts(r.get("max_extraido_en")) for r in _loaded(ctx, fqn)) if t]
        if not extracted:
            ev.append({"tipo": "frescura", "fuente": fqn, "estado": "UNKNOWN", "detalle": "sin entregas cargadas"})
            continue
        lags[fqn] = (max(extracted), warn_h, err_h)
    if not lags or ctx.as_of is None:
        return "UNKNOWN", "sin entregas cargadas para medir la frescura", ev, None

    last_sync = max(t for t, _, _ in lags.values())
    replica_lag = _hours(ctx.as_of - last_sync)
    limit = min(err_limits) if err_limits else None
    if limit is not None and replica_lag > limit:
        ev.insert(0, {"tipo": "frescura", "replica": "sin entregas", "retraso_horas": replica_lag, "error_after_h": limit})
        return "FAIL", f"la réplica no entrega desde hace {replica_lag} h (límite {limit} h)", ev, None
    for fqn, (t, warn_h, err_h) in sorted(lags.items()):
        lag = _hours(ctx.as_of - t)
        threshold = warn_h if warn_h is not None else err_h
        if threshold is not None and lag > threshold:
            ev.append({"tipo": "frescura", "fuente": fqn, "retraso_horas": lag, "detalle": "sin entregas recientes (puede no tener cambios)"})
    if ev:
        return "WARN", f"réplica al día; {len(ev)} fuente(s) sin entregas recientes", ev, None
    return "PASS", f"réplica al día (última entrega {replica_lag} h antes de as_of)", [], None


@check("OBS-02", "observability", "El producto refleja la última entrega", "runtime", "Hay entregas ingeridas que el producto no refleja: corre `dp build`.")
def obs_02(ctx, p):
    r = ctx.results.get(p.unique_id)
    if r is None:
        return "UNKNOWN", "el producto no aparece en la última corrida", [], None
    timing = {t.get("name"): t for t in r.get("timing") or []}
    built = _parse_ts((timing.get("execute") or {}).get("completed_at"))
    loaded = [t for t in (_parse_ts(x.get("ingerido_en")) for x in ctx.registry if x.get("estado") == "cargada") if t]
    if built is None or not loaded:
        return "UNKNOWN", "sin hora de construcción o sin entregas cargadas", [], None
    last = max(loaded)
    if built < last:
        return "FAIL", "hay entregas ingeridas después de la última construcción", [{"tipo": "frescura_producto", "construido": str(built), "ultima_ingesta": str(last)}], None
    return "PASS", "construido después de la última entrega ingerida", [], None


@check("OBS-03", "observability", "Volumen por entrega", "runtime", "Una entrega llegó vacía o fuera de rango: confirma con el dueño del origen antes de reprocesar.")
def obs_03(ctx, p):
    vol = ctx.policy.get("volume") or {}
    min_n, k = vol.get("min_deliveries") or 5, vol.get("band_k_mad") or 3
    worst, ev, notes = "PASS", [], []
    for uid in sorted(u for u in p.closure if u.startswith("source.")):
        fqn = _source_fqn(ctx, uid)
        rows = _loaded(ctx, fqn)
        if not rows:
            continue
        last = rows[-1]
        if (last.get("filas") or 0) == 0:
            ev.append({"tipo": "volumen", "fuente": fqn, "entrega": last.get("id_entrega"), "filas": 0})
            worst = "FAIL"
            continue
        if len(rows) < min_n:
            notes.append(fqn)
            continue
        hist = [x.get("filas") or 0 for x in rows[-min_n - 1:-1]]
        med = statistics.median(hist)
        mad = statistics.median([abs(x - med) for x in hist]) or 1
        if abs(last["filas"] - med) > k * mad:
            ev.append({"tipo": "volumen", "fuente": fqn, "filas": last["filas"], "mediana": med, "mad": mad})
            worst = "WARN" if worst == "PASS" else worst
    summary = "ninguna entrega vacía"
    if notes:
        summary += f"; banda sin juzgar en {len(notes)} fuentes (historial < {min_n} entregas)"
    if worst != "PASS":
        summary = f"{len(ev)} fuentes con volumen anómalo"
    return worst, summary, ev, None


@check("OBS-04", "observability", "Esquema de las entregas", "runtime", "La entrega cambió de esquema: una columna faltante se escala al dueño del origen; una nueva se registra en el YAML de la fuente.")
def obs_04(ctx, p):
    worst, ev = "PASS", []
    for uid in sorted(u for u in p.closure if u.startswith("source.")):
        fqn = _source_fqn(ctx, uid)
        rows = [r for r in ctx.registry if r.get("tabla_destino") == fqn]
        if not rows:
            continue
        last = rows[-1]
        if last.get("estado") == "rechazada":
            ev.append({"tipo": "esquema", "fuente": fqn, "entrega": last.get("id_entrega"), "rechazada": last.get("motivo")})
            worst = "FAIL"
        elif last.get("columnas_faltantes"):
            ev.append({"tipo": "esquema", "fuente": fqn, "entrega": last.get("id_entrega"), "columnas_faltantes": last["columnas_faltantes"]})
            worst = "FAIL"
        elif last.get("columnas_nuevas"):
            ev.append({"tipo": "esquema", "fuente": fqn, "entrega": last.get("id_entrega"), "columnas_nuevas": last["columnas_nuevas"]})
            worst = "WARN" if worst == "PASS" else worst
    return worst, ("esquema de las entregas igual al declarado" if worst == "PASS" else f"{len(ev)} fuentes con cambio de esquema"), ev, None


@check("OBS-06", "observability", "Estado del pipeline", "data", "Un modelo del linaje falló: revisa el primero que falló, no el último.")
def obs_06(ctx, p):
    nodes = sorted(u for u in p.closure | {p.unique_id} if u.startswith("model."))
    failed, unknown = [], []
    for uid in nodes:
        st = _status_of(ctx, uid)
        if st == "FAIL":
            r = ctx.results.get(uid) or {}
            failed.append({"tipo": "dbt_model", "ref": uid, "mensaje": str(r.get("message") or "").strip()[:300]})
        elif st == "UNKNOWN":
            unknown.append({"tipo": "dbt_model", "ref": uid, "estado": "sin resultado u omitido"})
    if failed:
        return "FAIL", f"{len(failed)} modelos del linaje fallaron", failed + unknown, None
    if unknown:
        return "UNKNOWN", f"{len(unknown)} modelos del linaje sin resultado", unknown, None
    return "PASS", f"{len(nodes)} modelos del linaje construidos", [], None


# ---------------------------------------------------------------- Performance / FinOps

SELECT_STAR = re.compile(r"select\s+\*\s+from", re.IGNORECASE)


@check("PRF-01", "performance", "Diseño para BigQuery", "design", "Declara partition_by y cluster_by en hechos grandes (o la razón de exención) y evita SELECT * en gold y mart.")
def prf_01(ctx, p):
    issues = []
    for uid in sorted((p.closure | {p.unique_id})):
        node = ctx.graph.nodes.get(uid)
        if not node or node.get("resource_type") != "model":
            continue
        cfg, meta = node.get("config") or {}, node.get("meta") or {}
        layer = (node.get("fqn") or [None, None])[1]
        exempt = (meta.get("performance") or {}).get("partition_exempt_reason")
        if node["name"].startswith("fct_") or uid == p.unique_id:
            if not exempt and not (cfg.get("partition_by") and cfg.get("cluster_by")):
                issues.append({"tipo": "particion", "ref": uid, "detalle": "sin partition_by/cluster_by ni razón de exención"})
        if layer in ("gold", "mart") and SELECT_STAR.search(node.get("raw_code") or ""):
            issues.append({"tipo": "select_estrella", "ref": uid})
    if issues:
        return "FAIL", f"{len(issues)} hallazgos de diseño para BigQuery", issues, None
    return "PASS", "hechos particionados y con clustering; marts agregados exentos con razón", [], None


@check("PRF-02", "performance", "Costo de construcción", "design", "Compara contra el presupuesto; si no hay, la corrida alimenta la línea base.")
def prf_02(ctx, p):
    budget = (ctx.policy.get("budgets") or {}).get(p.name)
    if not budget:
        return "PASS", "sin presupuesto definido: se registra la medición como línea base", [], None
    r = ctx.results.get(p.unique_id) or {}
    seconds = r.get("execution_time")
    limit = budget.get("max_build_seconds")
    if limit is not None and seconds is not None and seconds > limit:
        return "FAIL", f"construcción {seconds:.2f}s > presupuesto {limit}s", [{"tipo": "presupuesto", "medido_s": seconds, "limite_s": limit}], None
    return "PASS", "dentro del presupuesto", [], None
