"""Servidor MCP de `dp`: tres capacidades explícitas, sin autoridad propia.

Protocolo MCP estándar (JSON-RPC 2.0 por stdio, una línea por mensaje) con la biblioteca estándar,
para que funcione con Python 3.9 como el resto del estándar y con cualquier cliente MCP:

    .venv/bin/python -m dp.mcp

Reglas del diseño (las verifican las pruebas):
- Cada herramienta ejecuta `dp` como subproceso con argumentos fijos y sin shell: la lógica vive en
  `dp`, aquí solo se traduce la entrada y la salida.
- No hay herramientas genéricas (shell, SQL, dbt, git, GitHub) ni argumentos con los que construirlas.
- El servidor no usa credenciales de GitHub y se las quita al entorno de `dp`.
- Proponer no ejecuta: lo destructivo sigue pasando por el workflow `destructivo` y la aprobación
  humana en GitHub.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid

from dp import paths

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "dp", "title": "Estándar de ingeniería de datos", "version": "1.0.0"}
INSTRUCTIONS = (
    "Capacidades del estándar: consultar el estado (pipeline_status), diagnosticar (diagnose) y proponer "
    "una operación destructiva (propose_destructive_operation). Proponer nunca ejecuta: una persona la "
    "solicita y la aprueba en GitHub."
)
TIMEOUT_S = 300
# Ninguna credencial de GitHub llega a `dp` desde el servidor: ninguna capacidad la necesita.
CREDENCIALES = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "DP_AGENTE_GH_TOKEN")
PROPUESTAS_DIR = paths.EVIDENCE_DIR / "propuestas"
CERT_CATALOG = paths.ROOT / ".certification" / "catalogo.json"

_SIN_ARGUMENTOS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS = {
    "pipeline_status": {
        "title": "Estado del pipeline",
        "description": "READ. Estado de certificación de cada producto publicado (estado, salud, razones) y si "
                       "la certificación sigue vigente. Equivale a `dp certify status`. No modifica nada.",
        "inputSchema": _SIN_ARGUMENTOS,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "diagnose": {
        "title": "Diagnóstico",
        "description": "READ. Qué falló en la última corrida: nodo, regla, filas de muestra y mecanismos conocidos "
                       "del catálogo de chaos. Equivale a `dp diagnose --json`. No modifica nada.",
        "inputSchema": _SIN_ARGUMENTOS,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "propose_destructive_operation": {
        "title": "Proponer una operación destructiva",
        "description": "REQUEST. Genera una propuesta sellada (sha256) con clasificación, riesgo, impacto y "
                       "recomendación deterministas (`dp propose`). NO ejecuta nada: devuelve cómo debe "
                       "solicitarla una persona. Solo se ejecuta en el workflow `destructivo`, después de que "
                       "una persona la apruebe en el environment `produccion-destructiva` de GitHub.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operacion": {"type": "string", "enum": ["full-refresh", "recrear-producto", "cambio-contrato"]},
                "producto": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$",
                             "description": "producto afectado, o `todos`"},
                "motivo": {"type": "string", "minLength": 1, "maxLength": 500,
                           "description": "por qué se necesita; no influye en la recomendación"},
            },
            "required": ["operacion", "motivo"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    },
}


class EntradaInvalida(ValueError):
    pass


def validar(schema: dict, args) -> None:
    """El subconjunto de JSON Schema que usan las herramientas. Cualquier otra cosa se rechaza."""
    if not isinstance(args, dict):
        raise EntradaInvalida("los argumentos deben ser un objeto")
    props = schema["properties"]
    extra = sorted(set(args) - set(props))
    if extra:
        raise EntradaInvalida(f"argumentos no permitidos: {', '.join(extra)}")
    for nombre in schema.get("required", []):
        if nombre not in args:
            raise EntradaInvalida(f"falta el argumento `{nombre}`")
    for nombre, valor in args.items():
        regla = props[nombre]
        if not isinstance(valor, str):
            raise EntradaInvalida(f"`{nombre}` debe ser texto")
        if "enum" in regla and valor not in regla["enum"]:
            raise EntradaInvalida(f"`{nombre}` debe ser uno de: {', '.join(regla['enum'])}")
        if "pattern" in regla and not re.fullmatch(regla["pattern"], valor):
            raise EntradaInvalida(f"`{nombre}` no tiene un formato válido")
        if len(valor) < regla.get("minLength", 0) or len(valor) > regla.get("maxLength", len(valor)):
            raise EntradaInvalida(f"`{nombre}` tiene una longitud no permitida")
        if "\x00" in valor:
            raise EntradaInvalida(f"`{nombre}` contiene caracteres no permitidos")


def ejecutar_dp(*args: str) -> tuple:
    """Corre `dp` (con su guarda de plataforma) en la raíz del repo, sin shell y sin credenciales."""
    env = {k: v for k, v in os.environ.items() if k not in CREDENCIALES}
    proc = subprocess.run(
        [sys.executable, "-m", "dp.entrada", *args], cwd=str(paths.ROOT), env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_S,
    )
    return proc.returncode, proc.stdout, proc.stderr


def pipeline_status(_args: dict) -> tuple:
    code, out, err = ejecutar_dp("certify", "status")
    productos = []
    if CERT_CATALOG.exists():
        catalogo = json.loads(CERT_CATALOG.read_text(encoding="utf-8"))
        productos = [{"producto": p["product"], "estado": p["status"], "salud": p["health"], "razones": p["reasons"]}
                     for p in catalogo.get("products", [])]
    # La vigencia la decide `dp` (código 0); si no está vigente, el estado guardado no describe el actual.
    resultado = {"vigente": code == 0, "productos": productos, "detalle": (out or err).strip()}
    if code != 0:
        resultado["siguiente"] = "certificar de nuevo (`make all` o `dp certify run`)"
    return resultado, False


def diagnose(_args: dict) -> tuple:
    code, out, err = ejecutar_dp("diagnose", "--json")
    try:
        return {"hallazgos": json.loads(out)}, code != 0
    except json.JSONDecodeError:
        return {"error": (err or out).strip()[:2000]}, True


def _solicitud_humana(p: dict) -> dict:
    """Cómo pide una persona la operación: datos y pasos, nunca un comando de shell con texto del agente."""
    if p["operacion"] == "cambio-contrato":
        pasos = ["Un cambio de contrato no va por el workflow `destructivo`: va por PR, subiendo `meta.contract_version`.",
                 "GOV-07 lo marca como cambio gobernado y espera la aprobación de una persona en `aprobacion-estandar`."]
    else:
        pasos = ["En GitHub: Actions → workflow `destructivo` → Run workflow, sobre la rama `main`.",
                 "Captura en el formulario los valores de `entradas`.",
                 "En el resumen del job `plan`, revisa el Proposal ID, el SHA256, la clasificación y la recomendación "
                 "que sella GitHub: esa es la propuesta que se aprueba.",
                 "Aprueba o rechaza en el environment `produccion-destructiva`. Sin aprobación no se ejecuta nada."]
    return {
        "quien": "una persona; esta capacidad no puede solicitarla, aprobarla ni ejecutarla",
        "proposal_id": p["proposal_id"],
        "sha256": p.get("sha256"),
        # Datos para el formulario de GitHub, no para una shell: el motivo es texto del agente.
        "entradas": {"operacion": p["operacion"], "producto": p["producto"], "motivo": p["motivo"],
                     "simular_incidente": "ninguno"},
        "pasos": pasos,
    }


def propose_destructive_operation(args: dict) -> tuple:
    # El servidor elige el directorio de esta invocación: lee exactamente la propuesta que `dp` acaba
    # de sellar ahí, sin buscarla en una salida que incluye texto del agente (el motivo).
    salida = PROPUESTAS_DIR / f"mcp-{uuid.uuid4().hex}"
    # `--opcion=valor`: un motivo que empiece con "--" sigue siendo el valor, nunca otra opción.
    argv = ["propose", args["operacion"], f"--motivo={args['motivo']}", f"--salida={salida}"]
    if "producto" in args:
        argv.append(f"--producto={args['producto']}")
    code, out, err = ejecutar_dp(*argv)
    archivo = salida / "propuesta.json"
    if code != 0 or not archivo.is_file():
        return {"error": (out + err).strip()[-2000:]}, True
    p = json.loads(archivo.read_text(encoding="utf-8"))
    return {
        "proposal_id": p["proposal_id"],
        "sha256": p["sha256"],
        "commit": p["commit"],
        "operacion": p["operacion"],
        "producto": p["producto"],
        "clasificacion": p["clasificacion"],
        "riesgo": p["riesgo"],
        "recomendacion": p["recomendacion"],
        "afectados": [{k: a.get(k) for k in ("producto", "certificacion_publicado", "integridad",
                                              "filas_publicadas", "filas_reconstruccion")} for a in p["afectados"]],
        "impacto": p["impacto"],
        "estado": "PENDIENTE DE DECISIÓN HUMANA",
        "ejecutado": False,
        "solicitud_humana": _solicitud_humana(p),
        "archivo": os.path.relpath(archivo, paths.ROOT),
    }, False


HANDLERS = {
    "pipeline_status": pipeline_status,
    "diagnose": diagnose,
    "propose_destructive_operation": propose_destructive_operation,
}


def _resultado(datos: dict, es_error: bool) -> dict:
    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": texto}], "structuredContent": datos, "isError": es_error}


class ErrorRPC(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def llamar(params: dict) -> dict:
    nombre = params.get("name")
    if nombre not in HANDLERS:
        raise ErrorRPC(-32602, f"herramienta desconocida: {nombre}")
    try:
        validar(TOOLS[nombre]["inputSchema"], params.get("arguments") or {})
    except EntradaInvalida as exc:
        return _resultado({"error": str(exc)}, True)
    try:
        datos, es_error = HANDLERS[nombre](params.get("arguments") or {})
    except subprocess.TimeoutExpired:
        datos, es_error = {"error": f"`dp` no respondió en {TIMEOUT_S} s"}, True
    return _resultado(datos, es_error)


def atender(mensaje) -> dict | None:
    """Una petición JSON-RPC → su respuesta (None para notificaciones)."""
    if not isinstance(mensaje, dict) or mensaje.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "petición inválida"}}
    if "id" not in mensaje:
        return None
    metodo, params, ident = mensaje.get("method"), mensaje.get("params") or {}, mensaje["id"]
    try:
        if metodo == "initialize":
            pedida = params.get("protocolVersion")
            resultado = {
                "protocolVersion": pedida if pedida in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            }
        elif metodo == "ping":
            resultado = {}
        elif metodo == "tools/list":
            resultado = {"tools": [{"name": n, **spec} for n, spec in TOOLS.items()]}
        elif metodo == "tools/call":
            resultado = llamar(params)
        else:
            raise ErrorRPC(-32601, f"método no soportado: {metodo}")
    except ErrorRPC as exc:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": exc.code, "message": str(exc)}}
    return {"jsonrpc": "2.0", "id": ident, "result": resultado}


def main() -> int:
    # stdout es solo del protocolo; cualquier diagnóstico va a stderr.
    for linea in sys.stdin:
        if not linea.strip():
            continue
        try:
            respuesta = atender(json.loads(linea))
        except json.JSONDecodeError:
            respuesta = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}
        if respuesta is not None:
            sys.stdout.write(json.dumps(respuesta, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
