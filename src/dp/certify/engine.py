"""Evaluación y agregación: certificación = evaluate(evidencia, política).

Determinista: con la misma evidencia, la misma política y la misma versión del engine, el
resultado es el mismo. La única fuente de tiempo es `as_of`, que se deriva de la evidencia
(reloj replay) o se pasa explícito; nunca se lee la hora del sistema para evaluar.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import yaml

from dp import evidence
from dp.certify import ENGINE_VERSION
from dp.certify.checks import REGISTRY, CheckResult, Ctx, _parse_ts
from dp.certify.graph import Graph

HEALTH_ORDER = ["HEALTHY", "AT_RISK", "UNKNOWN", "STALE", "FAILED"]
FRESHNESS_CHECKS = {"OBS-01", "OBS-02"}


def load_policy(path: Path) -> tuple:
    raw = path.read_bytes()
    return yaml.safe_load(raw) or {}, "sha256:" + hashlib.sha256(raw).hexdigest()


def resolve_as_of(registry: list, explicit: str | None) -> tuple:
    if explicit:
        ts = _parse_ts(explicit)
        if ts is None:
            raise ValueError(f"--as-of inválido: {explicit}")
        return ts, "explicit"
    extracted = [t for t in (_parse_ts(r.get("max_extraido_en")) for r in registry if r.get("estado") == "cargada") if t]
    return (max(extracted) if extracted else None), "replay"


def _health(checks: list) -> str:
    worst = "HEALTHY"
    for c in checks:
        if c.phase != "runtime" or c.status in ("PASS", "NOT_APPLICABLE"):
            continue
        if c.status == "FAIL":
            h = "STALE" if c.id in FRESHNESS_CHECKS else "FAILED"
        elif c.status == "UNKNOWN":
            h = "UNKNOWN"
        else:
            h = "AT_RISK"
        worst = max(worst, h, key=HEALTH_ORDER.index)
    return worst


def _dimension_status(checks: list, dimension: str) -> str:
    sts = {c.status for c in checks if c.dimension == dimension}
    if sts & {"FAIL", "UNKNOWN"}:
        return "FAIL"
    if "WARN" in sts:
        return "WARN"
    return "PASS"


def aggregate(checks: list) -> tuple:
    """Devuelve (estado, salud, razones). La distinción clave es cómo se recupera el producto."""
    health = _health(checks)
    design_bad = [c.id for c in checks if c.phase == "design" and c.status in ("FAIL", "UNKNOWN")]
    if design_bad:
        return "NOT_CERTIFIED", health, design_bad
    if health in ("FAILED", "STALE", "UNKNOWN"):
        return "DEGRADED", health, [c.id for c in checks if c.phase == "runtime" and c.status in ("FAIL", "UNKNOWN")]
    warns = [c.id for c in checks if c.status == "WARN"]
    if warns:
        return "CERTIFIED_WITH_WARNINGS", health, warns
    return "CERTIFIED", health, []


def evaluate_product(ctx: Ctx, product, required: set, severities: dict) -> list:
    results = []
    data_phase = ctx.policy["contexts"][ctx.context].get("data_tests_phase", "runtime")
    for check_id in sorted(REGISTRY):
        spec = REGISTRY[check_id]
        status, summary, ev, counts = spec["fn"](ctx, product)
        phase = spec["phase"]
        if phase == "data":
            # El mismo test juzga la versión (CI, candidata) o los datos recibidos (operación).
            phase = data_phase
        severity = severities.get(check_id, "error")
        if check_id not in required and status == "UNKNOWN":
            status, summary = "NOT_APPLICABLE", f"no exigido en contexto {ctx.context}: {summary}"
        if severity == "warn" and status == "FAIL":
            status = "WARN"
        results.append(
            CheckResult(
                id=check_id,
                dimension=spec["dimension"],
                title=spec["title"],
                phase=phase,
                status=status,
                summary=summary,
                evidence=ev,
                counts=counts,
                owner=product.owner,
                severity=severity,
                recovery=spec["recovery"] if status not in ("PASS", "NOT_APPLICABLE") else None,
            )
        )
    return results


def _metrics(ctx: Ctx, product) -> dict:
    r = ctx.results.get(product.unique_id) or {}
    closure_models = [u for u in product.closure | {product.unique_id} if u.startswith("model.")]
    total = sum((ctx.results.get(u) or {}).get("execution_time") or 0 for u in closure_models)
    env = ctx.policy["contexts"][ctx.context].get("environment", "local-duckdb")

    def m(name, value, unit, provenance):
        return {"name": name, "value": value, "unit": unit, "provenance": provenance, "environment": env}

    na = "not_available"
    return {
        "build": [
            m("duration_ms", round((r.get("execution_time") or 0) * 1000), "ms", "measured" if r else na),
            m("lineage_duration_ms", round(total * 1000), "ms", "measured" if r else na),
            m("bytes_processed", None, "bytes", na),
            m("bytes_billed", None, "bytes", na),
            m("slot_ms", None, "ms", na),
            m("estimated_cost", None, "USD", na),
        ],
        "consumption": [
            {"exposure": e, "name": "queries_per_load", "value": None, "provenance": na, "environment": env}
            for e in ctx.graph.exposures_for(product)
        ],
    }


def certify(
    evidence_dir: Path,
    policy_path: Path,
    context: str = "run",
    as_of: str | None = None,
    base_manifest: Path | None = None,
    base_policy: Path | None = None,
    approved_by: str | None = None,
    generated_at: str | None = None,
) -> dict:
    manifest = evidence.load_json(evidence_dir / "manifest.json")
    run_results = evidence.load_json(evidence_dir / "run_results.json")
    if manifest is None:
        raise FileNotFoundError(f"no hay manifest en {evidence_dir}: corre `dp build` primero")
    registry = evidence.load_json(evidence_dir / "entregas.json") or []
    build = evidence.load_json(evidence_dir / "build.json") or {}
    policy, policy_digest = load_policy(policy_path)
    if context not in (policy.get("contexts") or {}):
        raise ValueError(f"contexto desconocido: {context}")
    ctx_policy = policy["contexts"][context]

    as_of_ts, clock = resolve_as_of(registry, as_of)
    base_graph = Graph(evidence.load_json(base_manifest)) if base_manifest and base_manifest.exists() else None
    policy_changed = None
    if base_policy is not None:
        policy_changed = (not base_policy.exists()) or base_policy.read_bytes() != policy_path.read_bytes()

    graph = Graph(manifest)
    ctx = Ctx(
        graph=graph,
        results={r["unique_id"]: r for r in (run_results or {}).get("results", [])},
        registry=registry,
        context=context,
        as_of=as_of_ts,
        policy=policy,
        idempotencia=evidence.load_json(evidence_dir / "idempotencia.json"),
        chaos=evidence.load_json(evidence_dir / "chaos_resultados.json"),
        base_graph=base_graph,
        policy_changed=policy_changed,
        approved_by=approved_by,
    )
    required = set(ctx_policy.get("required") or [])
    severities = {k: (v or {}).get("severity", "error") for k, v in (policy.get("checks") or {}).items()}
    generated_at = generated_at or evidence.utc_now()
    commit = build.get("commit", "desconocido")
    stamp = generated_at.replace("-", "").replace(":", "")
    evaluation = {
        "run_id": f"{stamp}_{commit}_{context}",
        "context": context,
        "environment": ctx_policy.get("environment", "local-duckdb"),
        "commit": commit,
        "clock": clock if clock == "explicit" else ctx_policy.get("clock", "replay"),
        "as_of": as_of_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if as_of_ts else None,
        "engine_version": ENGINE_VERSION,
        "policy_digest": policy_digest,
        "evidence_digest": evidence.evidence_digest(evidence_dir),
        "generated_at": generated_at,
        "last_build": {"finished_at": build.get("fin"), "exit_code": build.get("codigo_salida")},
    }

    products = []
    for p in graph.products():
        checks = evaluate_product(ctx, p, required, severities)
        status, health, reasons = aggregate(checks)
        products.append(
            {
                "schema_version": "1.0",
                "product": {
                    "id": p.name,
                    "dbt_unique_id": p.unique_id,
                    "relation": f"{p.node.get('schema')}.{p.node.get('alias') or p.name}",
                    "description": (p.node.get("description") or "").strip(),
                    "domain": p.group,
                    "owner": p.owner,
                    "technical_owner": p.meta.get("technical_owner"),
                    "criticality": p.meta.get("criticality"),
                    "sla": p.meta.get("sla"),
                    "grain": p.meta.get("grain"),
                    "primary_key": p.meta.get("primary_key"),
                    "contract_version": p.meta.get("contract_version"),
                    "business_rules": p.meta.get("business_rules") or [],
                },
                "evaluation": evaluation,
                "status": status,
                "health": health,
                "reasons": reasons,
                "dimensions": {
                    "testing": {"status": _dimension_status(checks, "testing")},
                    "observability": {"status": health},
                    "governance": {"status": _dimension_status(checks, "governance")},
                    "performance": {"status": _dimension_status(checks, "performance")},
                },
                "checks": [c.to_dict() for c in checks],
                "metrics": _metrics(ctx, p),
                "lineage": {
                    "sources": sorted(u for u in p.closure if u.startswith("source.")),
                    "upstream": sorted(u for u in p.closure if u.startswith("model.")),
                    "exposures": graph.exposures_for(p),
                },
            }
        )
    return {"evaluation": evaluation, "products": products}
