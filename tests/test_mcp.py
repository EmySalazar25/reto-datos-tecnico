"""Servidor MCP: capacidades explícitas sobre `dp`, sin autoridad propia.

Las garantías se prueban sobre el código y el protocolo, no sobre lo que un modelo decida hacer.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dp import cli, mcp

ROOT = Path(__file__).resolve().parents[1]
ESPERADAS = {"pipeline_status", "diagnose", "propose_destructive_operation"}
# Lo único que el servidor puede pedirle a `dp`.
SUBCOMANDOS_PERMITIDOS = {("certify", "status"), ("diagnose", "--json"), ("propose",)}


@pytest.fixture
def llamadas(monkeypatch, tmp_path):
    """Sustituye la ejecución de `dp` y registra cada argv que el servidor pide."""
    registro = []
    propuestas = tmp_path / ".evidence" / "propuestas"
    monkeypatch.setattr(mcp, "PROPUESTAS_DIR", propuestas)
    monkeypatch.setattr(mcp, "CERT_CATALOG", tmp_path / "catalogo.json")

    def falso(*args):
        registro.append(args)
        if args[0] == "propose":
            destino = propuestas / "PROP-1" / "propuesta.json"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps({
                "proposal_id": "PROP-1", "sha256": "sha256:" + "a" * 64, "commit": "c" * 40,
                "operacion": args[1], "producto": "todos", "clasificacion": "DESTRUCTIVE", "riesgo": "HIGH",
                "recomendacion": {"decision": "REJECT", "regla": "R5"}, "afectados": [], "impacto": [],
            }))
            salida = (f"## RECOMENDACIÓN\nPara solicitarla (nada se ejecuta hasta que una persona apruebe):\n"
                      f"  gh workflow run destructivo.yml -f operacion={args[1]} -f producto=todos -f motivo=\"x\"\n"
                      f"propuesta guardada en {destino}\n")
            return 0, salida, ""
        if args[0] == "diagnose":
            return 0, "[]", ""
        return 0, "embarques_mensual   CERTIFIED", ""

    monkeypatch.setattr(mcp, "ejecutar_dp", falso)
    return registro


def rpc(metodo, params=None, ident=1):
    return mcp.atender({"jsonrpc": "2.0", "id": ident, "method": metodo, "params": params or {}})


def herramienta(nombre, argumentos=None):
    return rpc("tools/call", {"name": nombre, "arguments": argumentos or {}})["result"]


# --- Protocolo ---------------------------------------------------------------------------------

def test_initialize_negocia_la_version():
    assert rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["protocolVersion"] == "2025-06-18"
    assert rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]
    assert rpc("initialize")["result"]["capabilities"] == {"tools": {"listChanged": False}}


def test_tools_list_expone_exactamente_las_tres_capacidades():
    tools = {t["name"]: t for t in rpc("tools/list")["result"]["tools"]}
    assert set(tools) == ESPERADAS
    for t in tools.values():
        assert t["inputSchema"]["additionalProperties"] is False
    assert tools["pipeline_status"]["annotations"]["readOnlyHint"] is True
    assert tools["diagnose"]["annotations"]["readOnlyHint"] is True
    assert tools["propose_destructive_operation"]["annotations"]["readOnlyHint"] is False


def test_metodos_y_herramientas_desconocidos_fallan_cerrado(llamadas):
    assert rpc("server/discover")["error"]["code"] == -32601
    for nombre in ("run_shell", "execute_sql", "run_dbt", "github_api", "execute_proposal", "approve"):
        assert rpc("tools/call", {"name": nombre, "arguments": {}})["error"]["code"] == -32602
    assert mcp.atender({"id": 1, "method": "tools/list"})["error"]["code"] == -32600
    assert mcp.atender({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert llamadas == []


# --- Funcionalidad: cada capacidad reutiliza `dp` -------------------------------------------------

def test_pipeline_status_reutiliza_dp_certify_status(llamadas, tmp_path):
    (tmp_path / "catalogo.json").write_text(json.dumps({"products": [
        {"product": "embarques_mensual", "status": "CERTIFIED", "health": "HEALTHY", "reasons": []}]}))
    r = herramienta("pipeline_status")
    assert llamadas == [("certify", "status")]
    assert r["isError"] is False and r["structuredContent"]["vigente"] is True
    assert r["structuredContent"]["productos"][0] == {"producto": "embarques_mensual", "estado": "CERTIFIED",
                                                      "salud": "HEALTHY", "razones": []}


def test_diagnose_reutiliza_dp_diagnose_json(llamadas):
    r = herramienta("diagnose")
    assert llamadas == [("diagnose", "--json")]
    assert r["structuredContent"] == {"hallazgos": []}


def test_proponer_no_ejecuta_y_devuelve_la_solicitud_humana(llamadas):
    r = herramienta("propose_destructive_operation", {"operacion": "full-refresh", "producto": "todos",
                                                      "motivo": "reconstruir"})
    datos = r["structuredContent"]
    assert llamadas == [("propose", "full-refresh", "--motivo=reconstruir", "--producto=todos")]
    assert datos["ejecutado"] is False and datos["estado"] == "PENDIENTE DE DECISIÓN HUMANA"
    assert datos["proposal_id"] == "PROP-1" and datos["recomendacion"]["decision"] == "REJECT"
    assert datos["solicitud_humana"]["comando"].startswith("gh workflow run destructivo.yml")


@pytest.mark.parametrize("argumentos", [
    {"operacion": "full-refresh"},                                        # falta el motivo
    {"operacion": "build", "motivo": "x"},                                # operación fuera de la lista
    {"operacion": "execute-proposal", "motivo": "x"},
    {"operacion": "full-refresh", "motivo": "x", "producto": "todos; rm -rf /"},
    {"operacion": "full-refresh", "motivo": "x", "producto": "../../.github"},
    {"operacion": "full-refresh", "motivo": "x" * 501},
    {"operacion": "full-refresh", "motivo": "x", "simular_incidente": "INC-01"},
    {"operacion": "full-refresh", "motivo": "x", "comando": "dbt build --full-refresh"},
    {"operacion": "full-refresh", "motivo": 7},
    "full-refresh",
])
def test_entradas_invalidas_fallan_cerrado_sin_llamar_a_dp(llamadas, argumentos):
    r = rpc("tools/call", {"name": "propose_destructive_operation", "arguments": argumentos})["result"]
    assert r["isError"] is True
    assert llamadas == []


# --- Seguridad: la autoridad no crece con el MCP --------------------------------------------------

def test_el_motivo_no_puede_inyectar_opciones_de_dp(llamadas):
    """Un motivo con forma de opción sigue siendo el motivo: no activa el incidente simulado."""
    herramienta("propose_destructive_operation", {"operacion": "full-refresh",
                                                  "motivo": "--simular-incidente=INC-01"})
    argv = list(llamadas[0])
    assert argv == ["propose", "full-refresh", "--motivo=--simular-incidente=INC-01"]
    parsed = cli.build_parser().parse_args(argv)
    assert parsed.simular_incidente is None and parsed.motivo == "--simular-incidente=INC-01"


def test_el_servidor_solo_puede_pedirle_a_dp_estado_diagnostico_y_propuesta(llamadas, tmp_path):
    herramienta("pipeline_status")
    herramienta("diagnose")
    for op in ("full-refresh", "recrear-producto", "cambio-contrato"):
        herramienta("propose_destructive_operation", {"operacion": op, "motivo": "x", "producto": "todos"})
    for argv in llamadas:
        assert argv[:2] in SUBCOMANDOS_PERMITIDOS or argv[:1] in SUBCOMANDOS_PERMITIDOS
        for prohibido in ("build", "--full-refresh", "execute-proposal", "verify-proposal", "chaos", "ingest",
                          "new-source", "--aprobacion", "--simular-incidente", "gh", "git"):
            assert prohibido not in argv


def test_dp_corre_sin_shell_sin_credenciales_y_con_su_guarda(monkeypatch):
    for variable in mcp.CREDENCIALES:
        monkeypatch.setenv(variable, "secreto-de-prueba")
    visto = {}

    def run(cmd, **kwargs):
        visto.update(cmd=cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, "[]", "")

    monkeypatch.setattr(mcp.subprocess, "run", run)
    mcp.ejecutar_dp("diagnose", "--json")
    assert visto["cmd"] == [sys.executable, "-m", "dp.entrada", "diagnose", "--json"]
    assert visto.get("shell") is not True and visto["stdin"] == subprocess.DEVNULL
    assert not set(mcp.CREDENCIALES) & set(visto["env"])


def test_el_modulo_no_tiene_red_shell_ni_logica_propia():
    """El servidor es un adaptador: sin red (no habla con GitHub), sin shell y sin importar la lógica de dp."""
    arbol = ast.parse((ROOT / "src" / "dp" / "mcp.py").read_text(encoding="utf-8"))
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados |= {f"{nodo.module}.{a.name}" if nodo.module == "dp" else nodo.module for a in nodo.names}
        elif isinstance(nodo, ast.keyword) and nodo.arg == "shell":
            pytest.fail("el servidor no debe usar shell")
        elif isinstance(nodo, ast.Attribute) and nodo.attr in ("system", "popen", "Popen"):
            pytest.fail(f"el servidor no debe usar {nodo.attr}")
    assert importados <= {"__future__", "json", "os", "re", "subprocess", "sys", "dp.paths"}


def test_la_superficie_del_mcp_es_ruta_protegida():
    from dp.certify import cambios

    patrones = cambios.codeowners_patterns((ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8"))
    for ruta in ("src/dp/mcp.py", ".mcp.json", "opencode.json"):
        assert cambios.is_protected(ruta, patrones), ruta


def test_las_configuraciones_de_cliente_lanzan_el_mismo_servidor():
    opencode = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))["mcp"]["dp"]
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["dp"]
    assert opencode["type"] == "local" and opencode["command"][-2:] == ["-m", "dp.mcp"]
    assert claude["args"] == ["-m", "dp.mcp"] and claude["command"].endswith(".venv/bin/python")


# --- Extremo a extremo por stdio, con `dp` real --------------------------------------------------

def test_stdio_extremo_a_extremo():
    entrada = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "prueba", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pipeline_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "propose_destructive_operation", "arguments": {"operacion": "borrar-todo", "motivo": "x"}}},
    ]
    proc = subprocess.run([sys.executable, "-m", "dp.mcp"], input="".join(json.dumps(m) + "\n" for m in entrada),
                          capture_output=True, text=True, timeout=120, cwd=ROOT)
    respuestas = [json.loads(l) for l in proc.stdout.splitlines()]   # stdout es solo JSON-RPC
    assert [r["id"] for r in respuestas] == [1, 2, 3, 4]
    assert {t["name"] for t in respuestas[1]["result"]["tools"]} == ESPERADAS
    estado = respuestas[2]["result"]
    assert estado["isError"] is False and set(estado["structuredContent"]) >= {"vigente", "productos", "detalle"}
    assert respuestas[3]["result"]["isError"] is True
