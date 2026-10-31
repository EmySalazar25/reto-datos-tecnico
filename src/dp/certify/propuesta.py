"""Gobernanza de operaciones destructivas: el agente propone, el sistema explica, una persona decide.

Todo aquí es determinista y vive en una ruta protegida (CODEOWNERS → GOV-07): la clasificación,
el riesgo, la recomendación, la huella de la propuesta y la verificación antes de ejecutar. El
LLM puede explicar el resultado, nunca producirlo.

Una propuesta es un JSON sellado con su sha256. La persona aprueba la corrida de GitHub que la
muestra; el job que ejecuta descarga la propuesta, recalcula la huella y ejecuta solo lo que la
propuesta dice. Cualquier diferencia detiene la ejecución (falla cerrado): aprobar A nunca
ejecuta B.
"""

from __future__ import annotations

import hashlib
import json
import re

ENVIRONMENT = "produccion-destructiva"
CERTIFIED = ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")

# Clasificación por definición del estándar, no por el efecto técnico local: en este repo los
# modelos son tablas y vistas, así que un full-refresh produce lo mismo que una corrida normal;
# lo destructivo es que descarta y reemplaza lo publicado (y en un warehouse con modelos
# incrementales, su historial).
CLASSIFICATION = {
    "corrida-normal": "SAFE",
    "full-refresh": "DESTRUCTIVE",
    "recrear-producto": "DESTRUCTIVE",
    "cambio-contrato": "CRITICAL",
}
BANNER = {
    "SAFE": "✅ SAFE — LOW RISK — NO APPROVAL REQUIRED",
    "DESTRUCTIVE": "⚠️ DESTRUCTIVE — {riesgo} RISK — HUMAN APPROVAL REQUIRED",
    "CRITICAL": "⛔ CRITICAL — CRITICAL RISK — HUMAN APPROVAL REQUIRED",
}


def classify(operation: str) -> str:
    if operation not in CLASSIFICATION:
        raise ValueError(f"operación desconocida: {operation}. Opciones: {', '.join(CLASSIFICATION)}")
    return CLASSIFICATION[operation]


def risk(classification: str, affected: list) -> str:
    if classification == "CRITICAL":
        return "CRITICAL"
    if classification == "SAFE":
        return "LOW"
    exposed = any(a.get("consumidores") or a.get("criticidad") == "alta" for a in affected)
    return "HIGH" if exposed else "MEDIUM"


def recommend(classification: str, affected: list) -> dict:
    """Recomendación determinista a partir de evidencia. No recibe el motivo ni la condición simulada.

    Certificación e integridad son dimensiones distintas: un producto puede pasar sus tests
    (CERTIFIED) y aun así no coincidir con la reconstrucción desde landing (DRIFTED).
    """
    if classification == "CRITICAL":
        return {"decision": "REJECT", "regla": "R1", "razon": (
            "Cambia el contrato de un producto publicado: rompe a sus consumidores y no se ejecuta como "
            "operación directa. Va por PR, con la aprobación de GOV-07.")}
    unknown = [a["producto"] for a in affected if a.get("integridad") not in ("INTACT", "DRIFTED")]
    if unknown:
        return {"decision": "REJECT", "regla": "R2", "razon": (
            f"No hay evidencia para comparar lo publicado con la reconstrucción desde landing ({', '.join(unknown)}): "
            "sin esa evidencia no se puede justificar asumir el riesgo.")}
    broken = [f"{a['producto']} {a.get('certificacion_reconstruccion')}" for a in affected
              if a.get("certificacion_reconstruccion") not in CERTIFIED]
    if broken:
        return {"decision": "REJECT", "regla": "R3", "razon": (
            f"La reconstrucción desde landing en este commit no certifica ({', '.join(broken)}): reconstruir no "
            "resolvería el problema, que está en el código o en los datos de origen. Se corrige con un PR o con "
            "una entrega nueva.")}
    drifted = [a for a in affected if a["integridad"] == "DRIFTED"]
    if drifted:
        detail = "; ".join(f"`{a['relacion']}`: {a.get('filas_publicadas')} filas publicadas vs "
                           f"{a.get('filas_reconstruccion')} en la reconstrucción" for a in drifted)
        return {"decision": "APPROVE", "regla": "R4", "razon": (
            f"Lo publicado no coincide con la reconstrucción determinista desde landing ({detail}). Landing es la "
            "fuente inmutable y la reconstrucción certifica: hay evidencia de que el estado publicado se alteró "
            "fuera del pipeline, y el full-refresh restaura el estado reproducible.")}
    if all(a.get("certificacion_publicado") in CERTIFIED for a in affected):
        return {"decision": "REJECT", "regla": "R5", "razon": (
            "El producto se encuentra certificado y publicado, y lo publicado coincide con la reconstrucción desde "
            "landing: no existe una condición operativa que justifique asumir el riesgo de una reconstrucción "
            "destructiva.")}
    return {"decision": "REJECT", "regla": "R0", "razon": (
        "Ninguna regla justifica la operación con la evidencia disponible.")}


def impact(operation: str, affected: list) -> list:
    names = ", ".join(f"`{a['producto']}`" for a in affected)
    consumers = sorted({c for a in affected for c in a.get("consumidores") or []})
    lines = []
    if operation == "cambio-contrato":
        lines.append(f"Rompe el contrato de {names} para sus consumidores ({', '.join(consumers) or 'sin consumidores'}).")
    else:
        lines += [
            f"Se descarta y reemplaza el estado publicado de {names}.",
            "Se reconstruyen las capas desde landing, que es inmutable.",
            f"Durante la operación, los consumidores ({', '.join(consumers) or 'ninguno declarado'}) podrían ver "
            "información incompleta.",
            "El producto no se considera publicado hasta recertificarse; si no certifica, no se publica.",
        ]
    for a in affected:
        if a.get("integridad") == "DRIFTED":
            lines.append(f"Se corrige la divergencia de `{a['relacion']}` ({a.get('filas_publicadas')} → "
                         f"{a.get('filas_reconstruccion')} filas).")
    return lines


def execution(proposal: dict) -> tuple:
    """Qué ejecuta una propuesta: (selección de dbt, full_refresh). Se deriva de la propuesta, no de los inputs."""
    op = proposal["operacion"]
    if op == "full-refresh":
        return None, True
    if op == "recrear-producto":
        return f"+{proposal['producto']}", True
    raise ValueError(f"la operación {op} no se ejecuta desde este workflow")


# --- Integridad de la propuesta --------------------------------------------------------------

def _content(proposal: dict) -> dict:
    return {k: v for k, v in proposal.items() if k not in ("sha256", "proposal_id")}


def fingerprint(proposal: dict) -> str:
    canonical = json.dumps(_content(proposal), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _proposal_id(content: dict, huella: str) -> str:
    fecha = re.sub(r"\D", "", content.get("generado_en", ""))[:8]
    return f"PROP-{fecha}-{huella.split(':', 1)[1][:8]}"


def seal(content: dict) -> dict:
    """Agrega la huella y el id derivado de ella. El id no necesita contador: sale del contenido."""
    huella = fingerprint(content)
    return {"proposal_id": _proposal_id(content, huella), "sha256": huella, **_content(content)}


def verify(proposal: dict, expected_sha256: str, context: dict) -> list:
    """Fallas de integridad; vacío = la propuesta es exactamente la que se revisó."""
    failures = []
    actual = fingerprint(proposal)
    if proposal.get("sha256") != actual:
        failures.append(f"la propuesta fue modificada: su contenido da {actual}, no {proposal.get('sha256')}")
    if actual != expected_sha256:
        failures.append(f"no es la propuesta revisada: se revisó {expected_sha256} y se intenta ejecutar {actual}")
    if proposal.get("proposal_id") != _proposal_id(proposal, actual):
        failures.append(f"el proposal_id {proposal.get('proposal_id')} no corresponde a su contenido")
    for key in ("commit", "corrida", "operacion", "producto"):
        if str(proposal.get(key)) != str(context.get(key)):
            failures.append(f"{key}: la propuesta dice {proposal.get(key)!r} y la ejecución {context.get(key)!r}")
    return failures


def authorize(proposal: dict, expected_sha256: str, context: dict, approvals: list) -> list:
    """Fallas que impiden ejecutar; vacío = hay aprobación humana y es para esta propuesta exacta."""
    failures = verify(proposal, expected_sha256, context)
    reviews = [a for a in approvals or [] if any(e.get("name") == ENVIRONMENT for e in a.get("environments") or [])]
    if any(a.get("state") == "rejected" for a in reviews):
        failures.append(f"la operación fue rechazada en {ENVIRONMENT}")
    elif not any(a.get("state") == "approved" for a in reviews):
        failures.append(f"no hay una aprobación humana en {ENVIRONMENT}")
    return failures


def approver(approvals: list) -> str | None:
    reviews = [a for a in approvals or [] if a.get("state") == "approved"
               and any(e.get("name") == ENVIRONMENT for e in a.get("environments") or [])]
    return reviews[-1]["user"]["login"] if reviews else None


def publishable(products: list) -> bool:
    """Después de ejecutar: solo se publica si cada producto vuelve a certificar."""
    return bool(products) and all(p["status"] in CERTIFIED for p in products)


# --- Presentación ----------------------------------------------------------------------------

def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render(p: dict) -> str:
    rec = p["recomendacion"]
    sim = p.get("condicion_simulada")
    fence = _fence(p["motivo"])
    afectados = p["afectados"]
    productos = ", ".join(f"`{a['producto']}`" for a in afectados)
    consumidores = ", ".join(sorted({c for a in afectados for c in a["consumidores"]})) or "-"
    contratos = ", ".join(f"`{a['producto']}` v{a['contrato']}" for a in afectados)
    reconstruccion = ", ".join(f"`{a['producto']}` {a['certificacion_reconstruccion']}" for a in afectados)
    lines = ["## ESTADO ACTUAL", "",
             "| Producto | Certificación de lo publicado | Integridad de la publicación | Filas publicadas / reconstrucción |",
             "|---|---|---|---|"]
    for a in afectados:
        lines.append(f"| `{a['producto']}` | {a['certificacion_publicado']} | {a['integridad']} | "
                     f"{a.get('filas_publicadas')} / {a.get('filas_reconstruccion')} |")
    lines += ["", "> Certificación e integridad son dimensiones distintas: un producto puede pasar sus tests "
              "(CERTIFIED) y aun así no coincidir con la reconstrucción determinista desde landing (DRIFTED)."]
    if sim:
        lines += ["", f"> ⚠️ **Condición simulada: {sim['id']}** — {sim['descripcion']}. {sim['nota']}"]
    lines += ["", "## CAMBIO PROPUESTO", "", f"**{BANNER[p['clasificacion']].format(riesgo=p['riesgo'])}**", "",
              "| | |", "|---|---|",
              f"| Proposal ID | `{p['proposal_id']}` |",
              f"| Operación | {p['operacion'].upper().replace('-', ' ')} |",
              f"| Clasificación | {p['clasificacion']} |",
              f"| Riesgo | {p['riesgo']} |",
              "| Estado | PENDING HUMAN APPROVAL |",
              "", "Texto del solicitante (no verificado, no influye en la recomendación):", "",
              f"{fence}text", p["motivo"], fence,
              "", "## ALCANCE", "",
              f"- Productos afectados: {productos}",
              f"- Consumidores afectados: {consumidores}",
              f"- Contratos: {contratos}",
              f"- Reconstrucción desde landing en este commit: {reconstruccion}",
              "", "## IMPACTO", ""]
    lines += [f"- {line}" for line in p["impacto"]]
    lines += ["", "## RECOMENDACIÓN DEL SISTEMA", "", f"**{rec['decision']}** (regla {rec['regla']})", "",
              f"Razón: {rec['razon']}", "",
              "> La recomendación es informativa. El sistema no puede autorizar esta operación.",
              "", "## INTEGRIDAD DE LA PROPUESTA", "", "| | |", "|---|---|",
              f"| Proposal ID | `{p['proposal_id']}` |",
              f"| Commit | `{p['commit']}` |",
              f"| Corrida | `{p['corrida']}` |",
              f"| SHA256 | `{p['sha256']}` |",
              "", "Aprobar en el environment autoriza exactamente esta propuesta: el job que ejecuta descarga este "
              "JSON, recalcula su SHA256 y no corre nada si no coincide.",
              "", "## DECISIÓN HUMANA REQUERIDA", "",
              f"- Environment: `{ENVIRONMENT}`",
              "- Estado: **WAITING FOR HUMAN DECISION**", ""]
    return "\n".join(lines)
