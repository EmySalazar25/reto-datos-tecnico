"""Propuesta de operación destructiva: el agente explica el impacto, una persona aprueba.

No ejecuta nada. Produce el plan (qué productos y consumidores se afectan, en qué estado están
y cuántas filas hay en juego) y el comando que envía la solicitud al workflow `destructivo`,
que espera la aprobación de un revisor en un environment de GitHub.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from dp import evidence

OPERATIONS = {
    "full-refresh": "Reconstruir todas las capas desde landing, descartando lo publicado.",
    "recrear-producto": "Borrar y volver a crear una tabla publicada fuera de la corrida normal.",
    "cambio-contrato": "Quitar o renombrar columnas, cambiar tipos o grano de un producto publicado.",
}


def _row_count(db_path: Path, relation: str):
    if not db_path.exists():
        return None
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(f"select count(*) from {relation}").fetchone()[0]
    except duckdb.Error:
        return None
    finally:
        con.close()


def plan(operation: str, product: str | None, reason: str, evidence_dir: Path, cert_dir: Path, db_path: Path) -> dict:
    if operation not in OPERATIONS:
        raise ValueError(f"operación desconocida: {operation}. Opciones: {', '.join(OPERATIONS)}")
    manifest = evidence.load_json(evidence_dir / "manifest.json") or {}
    public = {n["name"]: n for n in manifest.get("nodes", {}).values() if n.get("resource_type") == "model" and n.get("access") == "public"}
    if operation in ("recrear-producto", "cambio-contrato"):
        if not product or product not in public:
            raise ValueError(f"indica --producto con un producto publicado: {', '.join(sorted(public))}")
        targets = [product]
    else:
        targets = sorted(public)
    catalog = evidence.load_json(cert_dir / "catalogo.json") or {"products": []}
    status = {p["product"]: p["status"] for p in catalog["products"]}
    exposures = manifest.get("exposures", {})
    affected = []
    for name in targets:
        node = public[name]
        consumers = [e["name"] for e in exposures.values() if node["unique_id"] in ((e.get("depends_on") or {}).get("nodes") or [])]
        relation = f"{node.get('schema')}.{node.get('alias') or name}"
        affected.append({
            "producto": name, "relacion": relation, "dueno": node.get("group"),
            "contrato": (node.get("meta") or {}).get("contract_version"),
            "certificacion_actual": status.get(name, "sin certificar"),
            "consumidores": consumers, "filas_actuales": _row_count(db_path, relation),
        })
    request = None
    if operation != "cambio-contrato":
        request = f'gh workflow run destructivo.yml -f operacion={operation} -f producto={product or "todos"} -f motivo="{reason}"'
    return {"operacion": operation, "descripcion": OPERATIONS[operation], "motivo": reason,
            "afectados": affected, "generado_en": evidence.utc_now(), "solicitud": request}


def render(p: dict) -> str:
    lines = [f"# Propuesta: {p['operacion']}", "", p["descripcion"], "", f"**Motivo:** {p['motivo']}", "",
             "| Producto | Dueño | Contrato | Certificación actual | Consumidores | Filas actuales |", "|---|---|---|---|---|---|"]
    for a in p["afectados"]:
        lines.append(f"| `{a['producto']}` | {a['dueno']} | v{a['contrato']} | {a['certificacion_actual']} | "
                     f"{', '.join(a['consumidores']) or '-'} | {a['filas_actuales'] if a['filas_actuales'] is not None else 'n/d'} |")
    lines += ["", "**Impacto:** mientras la operación corre, los consumidores listados pueden ver la tabla vacía o "
              "incompleta; al terminar, el producto se recertifica antes de darse por publicado.", ""]
    if p["solicitud"]:
        lines += ["**Para solicitarla** (no se ejecuta hasta que un revisor apruebe en el environment "
                  "`produccion-destructiva`):", "", f"```bash\n{p['solicitud']}\n```"]
    else:
        lines += ["**Ruta:** un cambio de contrato va por PR subiendo `meta.contract_version`. CI lo marca "
                  "como cambio gobernado (GOV-07) y espera la aprobación del environment `aprobacion-estandar`."]
    return "\n".join(lines) + "\n"


def save(p: dict, evidence_dir: Path) -> Path:
    out = evidence_dir / "propuestas" / f"{p['generado_en'].replace(':', '')}_{p['operacion']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(p), encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
