"""Salidas de la certificación. Todo se deriva del JSON: no hay lógica de certificación aquí."""

from __future__ import annotations

import json
from pathlib import Path

ICON = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "UNKNOWN": "?", "NOT_APPLICABLE": "–",
        "HEALTHY": "✓", "AT_RISK": "⚠", "STALE": "✗", "FAILED": "✗"}
COUNT_LABELS = {"TST-01": "técnicos", "TST-04": "ingeniería", "TST-05": "negocio", "TST-06": "unit"}


def write_outputs(result: dict, out_dir: Path) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for prod in result["products"]:
        path = out_dir / f"{prod['product']['id']}.json"
        path.write_text(json.dumps(prod, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    catalog = [
        {
            "product": p["product"]["id"], "domain": p["product"]["domain"], "owner": p["product"]["owner"],
            "status": p["status"], "health": p["health"], "reasons": p["reasons"],
            "generated_at": p["evaluation"]["generated_at"],
        }
        for p in result["products"]
    ]
    (out_dir / "catalogo.json").write_text(
        json.dumps({"evaluation": result["evaluation"], "products": catalog}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "resumen.md").write_text(markdown_summary(result), encoding="utf-8")
    return paths


def _counts_line(prod: dict) -> str:
    parts = []
    for c in prod["checks"]:
        if c["id"] in COUNT_LABELS and c.get("counts"):
            parts.append(f"{COUNT_LABELS[c['id']]} {c['counts']['pasan']}/{c['counts']['total']}")
    return " · ".join(parts)


def _governed_section(cg: dict | None) -> list:
    """Lo que una persona aprueba en el environment: la lista exacta de cambios y su huella."""
    if not cg or not cg["cambios"]:
        return []
    a = cg.get("aprobacion") or {}
    if not a:
        estado = "**pendiente**"
    elif a.get("huella") == cg["huella"] and a.get("aprobado_por"):
        estado = f"aprobada por **{a['aprobado_por']}**" + (f" en el PR #{a['pr']}" if a.get("pr") else "")
    else:
        estado = f"**no corresponde** (la aprobación es de la huella `{a.get('huella')}`)"
    lines = [
        "",
        "### Cambios gobernados (GOV-07)",
        "",
        f"Huella `{cg['huella']}` · aprobación: {estado}",
        "",
        "Aprobar es aprobar exactamente esta lista. Si cambia, la huella cambia y la aprobación deja de valer.",
        "",
    ]
    lines += [f"- `{json.dumps(c, ensure_ascii=False)}`" for c in cg["cambios"]]
    return lines


def markdown_summary(result: dict) -> str:
    ev = result["evaluation"]
    lines = [
        "## Certificación de productos de datos",
        "",
        f"commit `{ev['commit']}` · contexto `{ev['context']}` · entorno `{ev['environment']}` · "
        f"reloj `{ev['clock']}` (as_of {ev['as_of']}) · engine {ev['engine_version']}",
        "",
    ]
    if ev["clock"] != "wall":
        lines += [
            "> Reloj **" + ev["clock"] + "**: la frescura se mide contra la última entrega (o contra `as_of`), "
            "no contra la hora real. Un `HEALTHY` aquí no significa frescura productiva.",
            "",
        ]
    lines += [
        "| Producto | Dominio | Dueño | Testing | Observabilidad | Gobernanza | Performance | Certificación |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in result["products"]:
        d = p["dimensions"]
        lines.append(
            f"| `{p['product']['id']}` | {p['product']['domain']} | {p['product']['owner']} | "
            f"{ICON[d['testing']['status']]} {d['testing']['status']} | "
            f"{ICON[d['observability']['status']]} {d['observability']['status']} | "
            f"{ICON[d['governance']['status']]} {d['governance']['status']} | "
            f"{ICON[d['performance']['status']]} {d['performance']['status']} | **{p['status']}** |"
        )
    lines += _governed_section(ev.get("cambios_gobernados"))
    for p in result["products"]:
        lines += ["", f"### `{p['product']['id']}` — {p['status']}", ""]
        lines.append(f"Testing: {_counts_line(p)}  ")
        lines.append(
            f"Contrato v{p['product']['contract_version']} · grano {p['product']['grain']} · "
            f"consumidores {len(p['lineage']['exposures'])} · reglas {', '.join(r['id'] for r in p['product']['business_rules'])}"
        )
        problems = [c for c in p["checks"] if c["status"] not in ("PASS", "NOT_APPLICABLE")]
        if not problems:
            lines.append("")
            lines.append("Todos los checks exigidos pasan.")
        for c in problems:
            lines += ["", f"- {ICON[c['status']]} **{c['id']} {c['title']}** ({c['phase']}): {c['summary']}"]
            for item in c.get("evidence", [])[:5]:
                lines.append(f"  - `{json.dumps(item, ensure_ascii=False)}`")
            if c.get("recovery"):
                lines.append(f"  - Recuperación: {c['recovery']}")
        na = [c["id"] for c in p["checks"] if c["status"] == "NOT_APPLICABLE"]
        if na:
            lines += ["", f"No exigidos en este contexto: {', '.join(na)}"]
    lines.append("")
    return "\n".join(lines)


def agent_status(prod: dict, stale: tuple = ((), None)) -> str:
    """Salida compacta para un LLM: estado, razones y la evidencia mínima de cada razón.

    Si la certificación guardada está desactualizada, no se muestra como estado actual.
    """
    reasons, command = stale
    if reasons:
        return "\n".join(
            [f"producto: {prod['product']['id']}",
             f"estado: DESACTUALIZADA (la última certificación, del {prod['evaluation']['generated_at']}, "
             f"dijo {prod['status']}; no describe el estado actual)"]
            + [f"por qué: {r}" for r in reasons]
            + [f"siguiente: {command}"]
        )
    lines = [
        f"producto: {prod['product']['id']}",
        f"estado: {prod['status']}",
        f"salud: {prod['health']} (reloj {prod['evaluation']['clock']}, as_of {prod['evaluation']['as_of']})",
        f"razones: {', '.join(prod['reasons']) or 'ninguna'}",
    ]
    by_id = {c["id"]: c for c in prod["checks"]}
    unknown = [rid for rid in prod["reasons"] if by_id[rid]["status"] == "UNKNOWN"]
    for rid in prod["reasons"]:
        c = by_id[rid]
        if c["status"] == "UNKNOWN" and len(unknown) < len(prod["reasons"]):
            continue  # consecuencias de la falla principal: se resumen abajo
        lines.append(f"{rid} {c['status']} [{c['phase']}] {c['title']}: {c['summary']}")
        for item in c.get("evidence", [])[:3]:
            compact = {k: v for k, v in item.items() if k != "mensaje"}
            lines.append(f"  evidencia: {json.dumps(compact, ensure_ascii=False)}")
    if unknown and len(unknown) < len(prod["reasons"]):
        lines.append(f"sin evidencia (consecuencia: nodos omitidos tras la falla): {', '.join(unknown)}")
    if prod["reasons"]:
        lines.append(f"siguiente: dp certify explain {prod['product']['id']} {prod['reasons'][0]}")
    return "\n".join(lines)
