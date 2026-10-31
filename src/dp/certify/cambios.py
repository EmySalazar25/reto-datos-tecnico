"""Cambios gobernados (GOV-07) y su huella.

Una persona no aprueba un nombre ni un commit: aprueba un conjunto exacto de cambios. La huella
es el sha256 de la lista canónica de cambios con su valor antes y después. No depende de los
commits ni del orden, así que el PR y el merge del mismo cambio producen la misma huella, y
cualquier cambio distinto (o el mismo cambio modificado después de aprobarlo) produce otra.

Son cambios gobernados los que rompen el contrato de un producto, los que debilitan el estándar
(borrar reglas o tests, bajar severidad, editar la política) y los que tocan una ruta protegida:
las rutas de CODEOWNERS en la versión base (el motor, el CI, la política y la configuración del
agente).
"""

from __future__ import annotations

import hashlib
import json
from fnmatch import fnmatch
from pathlib import Path

from dp.certify.graph import Graph, Product

GOVERNED_TEST_KINDS = ("business", "engineering", "unit")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def contract_columns(node: dict) -> dict:
    return {c: (v.get("data_type") or "").lower() for c, v in (node.get("columns") or {}).items()}


def product_changes(graph: Graph, base_graph: Graph, product: Product) -> list:
    """Cambios gobernados de un producto contra su versión base."""
    base_node = base_graph.nodes.get(product.unique_id)
    if base_node is None:
        return []
    changes = []
    before, after = contract_columns(base_node), contract_columns(product.node)
    removed = sorted(set(before) - set(after))
    retyped = sorted(c for c in before if c in after and before[c] != after[c])
    if removed or retyped:
        bumped = (product.meta.get("contract_version") or 0) > ((base_node.get("meta") or {}).get("contract_version") or 0)
        changes.append({
            "tipo": "contrato_incompatible", "producto": product.name, "columnas_eliminadas": removed,
            "tipos_cambiados": retyped, "tipos": {c: [before[c], after[c]] for c in retyped},
            "contract_version_subio": bumped,
        })
    base_rules = {r.get("id") for r in (base_node.get("meta") or {}).get("business_rules") or []}
    now_rules = {r.get("id") for r in product.meta.get("business_rules") or []}
    if base_rules - now_rules:
        changes.append({"tipo": "reglas_eliminadas", "producto": product.name, "reglas": sorted(base_rules - now_rules)})
    base_p = next((bp for bp in base_graph.products() if bp.unique_id == product.unique_id), None)
    if base_p is not None:
        now_tests = {t.unique_id: t for t in graph.tests_for(product)}
        for t in base_graph.tests_for(base_p):
            if t.kind not in GOVERNED_TEST_KINDS and t.generic_name != "combinacion_unica":
                continue
            if t.unique_id not in now_tests:
                changes.append({"tipo": "test_eliminado", "ref": t.unique_id, "regla": t.rule})
            elif t.severity == "error" and now_tests[t.unique_id].severity == "warn":
                changes.append({"tipo": "severidad_rebajada", "ref": t.unique_id, "regla": t.rule,
                                "antes": "error", "despues": "warn"})
    return changes


def policy_change(base_policy: Path | None, policy_path: Path) -> dict | None:
    if base_policy is None:
        return None
    after = _sha256(policy_path.read_bytes())
    before = _sha256(base_policy.read_bytes()) if base_policy.exists() else None
    if before == after:
        return None
    return {"tipo": "politica_modificada", "archivo": "standard/policy.yml", "antes": before, "despues": after}


def codeowners_patterns(text: str) -> list:
    patterns = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            patterns.append(line.split()[0])
    return patterns


def is_protected(path: str, patterns: list) -> bool:
    """Subconjunto de la sintaxis de CODEOWNERS: rutas ancladas (`/dir/`, `/archivo`), sin anclar y comodines."""
    for pattern in patterns:
        anchored = pattern.startswith("/")
        pat = pattern.lstrip("/")
        candidates = [path]
        if not anchored:
            candidates += [path.split("/", i)[-1] for i in range(1, path.count("/") + 1)]
        for candidate in candidates:
            if fnmatch(candidate, pat) or candidate.startswith(pat.rstrip("/") + "/"):
                return True
    return False


def parse_raw_diff(data: bytes) -> list:
    """Lee la salida de `git diff --raw -z --no-abbrev --no-renames <base> <head>`."""
    parts = data.split(b"\0")
    entries = []
    for meta, path in zip(parts[0::2], parts[1::2]):
        if not meta.startswith(b":"):
            continue
        _, _, before, after, status = meta[1:].decode().split()[:5]
        entries.append({"archivo": path.decode("utf-8", "surrogateescape"), "antes": before, "despues": after,
                        "estado": status})
    return entries


def protected_changes(diff: bytes, codeowners: str) -> list:
    """Archivos de rutas protegidas que cambiaron, con el blob exacto antes y después."""
    patterns = codeowners_patterns(codeowners)
    return [
        {"tipo": "ruta_protegida", "archivo": e["archivo"], "antes": e["antes"], "despues": e["despues"]}
        for e in parse_raw_diff(diff)
        if is_protected(e["archivo"], patterns)
    ]


def _canonical(change: dict) -> str:
    return json.dumps(change, sort_keys=True, ensure_ascii=False)


def unique_sorted(changes: list) -> list:
    by_key = {_canonical(c): c for c in changes}
    return [by_key[k] for k in sorted(by_key)]


def fingerprint(changes: list) -> str | None:
    """Huella del conjunto de cambios: igual solo si los cambios son exactamente los mismos."""
    if not changes:
        return None
    return _sha256("\n".join(sorted({_canonical(c) for c in changes})).encode("utf-8"))


def short(huella: str | None) -> str:
    return huella[:19] if huella else "—"
