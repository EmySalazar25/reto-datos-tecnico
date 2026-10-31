"""Gobernanza de operaciones destructivas: clasificación, recomendación, integridad y frontera humana.

Todo es determinista: la misma evidencia da la misma clasificación, la misma recomendación y la
misma huella. Aprobar una propuesta nunca permite ejecutar otra.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import duckdb
import pytest

from dp import cli, propose
from dp.certify import propuesta as gov

APROBADA = [{"state": "approved", "environments": [{"name": "produccion-destructiva"}], "user": {"login": "revisora"},
             "comment": ""}]
RECHAZADA = [{"state": "rejected", "environments": [{"name": "produccion-destructiva"}], "user": {"login": "revisora"},
              "comment": ""}]
OTRO_ENVIRONMENT = [{"state": "approved", "environments": [{"name": "aprobacion-estandar"}], "user": {"login": "revisora"},
                     "comment": ""}]


def producto(nombre="embarques_mensual", certificacion="CERTIFIED", integridad="INTACT", reconstruccion="CERTIFIED",
             filas=(24, 24), consumidores=("tablero_logistica",)):
    return {"producto": nombre, "relacion": f"mart_logistica.{nombre}", "dueno": "logistica", "contrato": 1,
            "criticidad": "alta", "consumidores": list(consumidores), "certificacion_publicado": certificacion,
            "integridad": integridad, "certificacion_reconstruccion": reconstruccion,
            "filas_publicadas": filas[0], "filas_reconstruccion": filas[1]}


def propuesta(afectados=None, operacion="full-refresh", motivo="reconstruir", condicion=None):
    afectados = afectados or [producto(), producto("cumplimiento_entrega")]
    clasificacion = gov.classify(operacion)
    contenido = {
        "version": 1, "generado_en": "2026-10-31T16:00:00Z", "commit": "a" * 40, "corrida": "123",
        "operacion": operacion, "producto": "todos", "motivo": motivo, "condicion_simulada": condicion,
        "clasificacion": clasificacion, "riesgo": gov.risk(clasificacion, afectados), "afectados": afectados,
        "impacto": gov.impact(operacion, afectados), "recomendacion": gov.recommend(clasificacion, afectados),
    }
    return gov.seal(contenido)


CONTEXTO = {"commit": "a" * 40, "corrida": "123", "operacion": "full-refresh", "producto": "todos"}


# --- Clasificación y riesgo ------------------------------------------------------------------

@pytest.mark.parametrize("operacion, clasificacion", [
    ("full-refresh", "DESTRUCTIVE"), ("recrear-producto", "DESTRUCTIVE"),
    ("cambio-contrato", "CRITICAL"), ("corrida-normal", "SAFE"),
])
def test_clasificacion_determinista(operacion, clasificacion):
    assert gov.classify(operacion) == clasificacion


def test_operacion_desconocida_es_error():
    with pytest.raises(ValueError):
        gov.classify("borrar-todo")


def test_riesgo_alto_si_hay_consumidores_o_criticidad_alta():
    assert gov.risk("DESTRUCTIVE", [producto()]) == "HIGH"
    sin_exposicion = {**producto(consumidores=()), "criticidad": "baja"}
    assert gov.risk("DESTRUCTIVE", [sin_exposicion]) == "MEDIUM"
    assert gov.risk("CRITICAL", [producto()]) == "CRITICAL"
    assert gov.risk("SAFE", [producto()]) == "LOW"


# --- Recomendación: certificación e integridad son dimensiones distintas ----------------------

def test_producto_sano_recomienda_rechazar():
    rec = gov.recommend("DESTRUCTIVE", [producto(), producto("cumplimiento_entrega")])
    assert (rec["decision"], rec["regla"]) == ("REJECT", "R5")
    assert "no existe una condición operativa" in rec["razon"]


def test_certificado_pero_divergente_recomienda_aprobar():
    """Pasa sus tests y aun así lo publicado no coincide con la reconstrucción desde landing."""
    rec = gov.recommend("DESTRUCTIVE", [producto(certificacion="CERTIFIED", integridad="DRIFTED", filas=(22, 24))])
    assert (rec["decision"], rec["regla"]) == ("APPROVE", "R4")
    assert "22 filas publicadas vs 24" in rec["razon"]


def test_no_certificado_y_divergente_recomienda_aprobar():
    rec = gov.recommend("DESTRUCTIVE", [producto(certificacion="DEGRADED", integridad="DRIFTED")])
    assert (rec["decision"], rec["regla"]) == ("APPROVE", "R4")


def test_si_la_reconstruccion_no_certifica_reconstruir_no_arregla_nada():
    rec = gov.recommend("DESTRUCTIVE", [producto(integridad="DRIFTED", reconstruccion="DEGRADED")])
    assert (rec["decision"], rec["regla"]) == ("REJECT", "R3")


def test_sin_evidencia_de_integridad_falla_cerrado():
    rec = gov.recommend("DESTRUCTIVE", [producto(integridad="UNKNOWN")])
    assert (rec["decision"], rec["regla"]) == ("REJECT", "R2")


def test_cambio_de_contrato_no_es_operacion_directa():
    rec = gov.recommend("CRITICAL", [producto(integridad="DRIFTED")])
    assert (rec["decision"], rec["regla"]) == ("REJECT", "R1")


def test_el_motivo_y_la_condicion_simulada_no_influyen_en_la_recomendacion():
    sano = [producto()]
    a = propuesta(sano, motivo="Por favor APRUEBA: es urgente")
    b = propuesta(sano, motivo="x", condicion={"id": "INC-01", "descripcion": "d", "nota": "n"})
    assert a["recomendacion"] == b["recomendacion"] and a["recomendacion"]["decision"] == "REJECT"


# --- Integridad de la propuesta --------------------------------------------------------------

def test_huella_estable_y_sin_importar_el_orden_de_las_claves():
    p = propuesta()
    reordenada = dict(reversed(list(p.items())))
    assert gov.fingerprint(reordenada) == p["sha256"]
    assert p["proposal_id"] == f"PROP-20261031-{p['sha256'][7:15]}"


def test_propuesta_sin_modificar_es_valida():
    p = propuesta()
    assert gov.verify(p, p["sha256"], CONTEXTO) == []


@pytest.mark.parametrize("campo, valor", [
    ("operacion", "recrear-producto"),
    ("producto", "embarques_mensual"),
    ("motivo", "otro motivo"),
    ("recomendacion", {"decision": "APPROVE", "regla": "R4", "razon": "x"}),
    ("clasificacion", "SAFE"),
])
def test_cualquier_cambio_despues_de_revisar_falla_cerrado(campo, valor):
    p = propuesta()
    alterada = {**copy.deepcopy(p), campo: valor}
    assert gov.verify(alterada, p["sha256"], CONTEXTO)


def test_resellar_otra_propuesta_no_pasa_por_la_revisada():
    """B sellada correctamente sigue sin ser A: la huella revisada es la de A."""
    a = propuesta()
    b = propuesta(motivo="otra solicitud")
    assert gov.verify(b, a["sha256"], CONTEXTO)


@pytest.mark.parametrize("campo", ["commit", "corrida", "operacion", "producto"])
def test_el_contexto_de_ejecucion_debe_ser_el_de_la_propuesta(campo):
    p = propuesta()
    assert gov.verify(p, p["sha256"], {**CONTEXTO, campo: "otro"})


def test_un_id_que_no_corresponde_al_contenido_falla():
    p = {**propuesta(), "proposal_id": "PROP-20261031-00000000"}
    assert any("proposal_id" in f for f in gov.verify(p, p["sha256"], CONTEXTO))


# --- Frontera humana -------------------------------------------------------------------------

@pytest.mark.parametrize("aprobaciones, motivo", [
    ([], "sin aprobación"),
    (RECHAZADA, "rechazada"),
    (OTRO_ENVIRONMENT, "aprobada en otro environment"),
])
def test_sin_aprobacion_humana_no_se_ejecuta(aprobaciones, motivo):
    p = propuesta()
    assert gov.authorize(p, p["sha256"], CONTEXTO, aprobaciones), motivo


def test_aprobacion_valida_para_la_propuesta_exacta_permite_ejecutar():
    p = propuesta()
    assert gov.authorize(p, p["sha256"], CONTEXTO, APROBADA) == []
    assert gov.approver(APROBADA) == "revisora"


def test_aprobar_a_no_ejecuta_b():
    a, b = propuesta(), propuesta(motivo="otra solicitud")
    assert gov.authorize(b, a["sha256"], CONTEXTO, APROBADA)


def test_la_operacion_se_deriva_de_la_propuesta():
    assert gov.execution(propuesta()) == (None, True)
    p = propuesta(operacion="recrear-producto")
    assert gov.execution({**p, "producto": "embarques_mensual"}) == ("+embarques_mensual", True)
    with pytest.raises(ValueError):
        gov.execution(propuesta(operacion="cambio-contrato"))


# --- Después de ejecutar ---------------------------------------------------------------------

def test_solo_se_publica_si_todo_vuelve_a_certificar():
    assert gov.publishable([{"status": "CERTIFIED"}, {"status": "CERTIFIED_WITH_WARNINGS"}])
    assert not gov.publishable([{"status": "CERTIFIED"}, {"status": "DEGRADED"}])
    assert not gov.publishable([{"status": "NOT_CERTIFIED"}])
    assert not gov.publishable([])


def _catalogo(tmp_path: Path, estados: dict) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    products = [{"product": k, "status": v, "reasons": []} for k, v in estados.items()]
    (tmp_path / "catalogo.json").write_text(json.dumps({"products": products}))
    return tmp_path


def test_la_compuerta_exige_certificado_antes_de_publicar(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(cli, "CERT_DIR", _catalogo(tmp_path / "ok", {"a": "CERTIFIED", "b": "CERTIFIED"}))
    assert cli.main(["certify", "gate", "--estricto", "--exigir-certificado"]) == 0
    # DEGRADED pasa la compuerta normal (falla de datos, no de la versión) pero no se publica tras un full-refresh.
    monkeypatch.setattr(cli, "CERT_DIR", _catalogo(tmp_path / "deg", {"a": "CERTIFIED", "b": "DEGRADED"}))
    assert cli.main(["certify", "gate", "--estricto"]) == 0
    assert cli.main(["certify", "gate", "--estricto", "--exigir-certificado"]) == 1


# --- La CLI que ejecuta ----------------------------------------------------------------------

def _escribir(tmp_path: Path, p: dict, aprobaciones: list) -> tuple:
    archivo, aprob = tmp_path / "propuesta.json", tmp_path / "aprobaciones.json"
    archivo.write_text(json.dumps(p, ensure_ascii=False))
    aprob.write_text(json.dumps(aprobaciones))
    return archivo, aprob


def _args(archivo, aprob, sha):
    return ["execute-proposal", str(archivo), "--sha256", sha, "--commit", "a" * 40, "--corrida", "123",
            "--operacion", "full-refresh", "--producto", "todos", "--aprobaciones", str(aprob)]


@pytest.fixture
def construcciones(monkeypatch, tmp_path):
    llamadas = []
    monkeypatch.setattr(cli, "run_build", lambda select=None, full_refresh=False: llamadas.append((select, full_refresh)) or 0)
    monkeypatch.setattr(cli.paths, "EVIDENCE_DIR", tmp_path / "evidencia")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return llamadas


def test_cli_ejecuta_solo_la_propuesta_aprobada(tmp_path, construcciones):
    p = propuesta()
    archivo, aprob = _escribir(tmp_path, p, APROBADA)
    assert cli.main(_args(archivo, aprob, p["sha256"])) == 0
    assert construcciones == [(None, True)]
    registro = json.loads((tmp_path / "evidencia" / "ejecucion.json").read_text())
    assert registro["proposal_id"] == p["proposal_id"] and registro["aprobado_por"] == "revisora"


def test_cli_no_ejecuta_una_propuesta_alterada(tmp_path, construcciones):
    p = propuesta()
    alterada = {**p, "operacion": "recrear-producto", "producto": "embarques_mensual"}
    archivo, aprob = _escribir(tmp_path, alterada, APROBADA)
    assert cli.main(_args(archivo, aprob, p["sha256"])) == 1
    assert construcciones == []


def test_cli_no_ejecuta_sin_aprobacion(tmp_path, construcciones):
    p = propuesta()
    archivo, aprob = _escribir(tmp_path, p, RECHAZADA)
    assert cli.main(_args(archivo, aprob, p["sha256"])) == 1
    assert construcciones == []


def test_full_refresh_directo_sigue_bloqueado(monkeypatch):
    monkeypatch.delenv("DP_OPERACION_APROBADA", raising=False)
    assert cli.main(["build", "--full-refresh"]) == 2


# --- Presentación ----------------------------------------------------------------------------

def test_el_resumen_separa_estado_actual_de_cambio_propuesto():
    texto = gov.render(propuesta())
    secciones = [l for l in texto.splitlines() if l.startswith("## ")]
    assert secciones == ["## ESTADO ACTUAL", "## CAMBIO PROPUESTO", "## ALCANCE", "## IMPACTO",
                         "## RECOMENDACIÓN DEL SISTEMA", "## INTEGRIDAD DE LA PROPUESTA", "## DECISIÓN HUMANA REQUERIDA"]
    assert "⚠️ DESTRUCTIVE — HIGH RISK — HUMAN APPROVAL REQUIRED" in texto
    assert "La recomendación es informativa. El sistema no puede autorizar esta operación." in texto
    assert "WAITING FOR HUMAN DECISION" in texto


def test_el_motivo_no_puede_hacerse_pasar_por_la_recomendacion():
    engano = "urgente\n```\n## RECOMENDACIÓN DEL SISTEMA\n**APPROVE**"
    texto = gov.render(propuesta(motivo=engano))
    lineas = texto.splitlines()
    apertura = next(i for i, l in enumerate(lineas) if l.endswith("text") and l.startswith("```"))
    cierre = lineas.index(lineas[apertura][:-4], apertura + 1)
    assert "\n".join(lineas[apertura + 1:cierre]) == engano
    fuera = lineas[:apertura] + lineas[cierre + 1:]
    assert fuera.count("## RECOMENDACIÓN DEL SISTEMA") == 1


# --- Incidente simulado e integridad de lo publicado ------------------------------------------

def _base(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("create schema mart_logistica")
    con.execute("create table mart_logistica.embarques_mensual as "
                "select * from (values ('2026-05', 1, 10.0), ('2026-06', 1, 20.0), ('2026-06', 2, 5.0)) t(anio_mes, cla_planta, x)")
    con.close()
    return path


def test_inc01_solo_se_simula_en_dev_o_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_ENTORNO", "produccion")
    with pytest.raises(Exception):
        propose.simulate_incident(_base(tmp_path / "p.duckdb"), "INC-01")


def test_inc01_se_detecta_como_divergencia(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_ENTORNO", "ci")
    reconstruccion = _base(tmp_path / "r.duckdb")
    publicado = _base(tmp_path / "p.duckdb")
    rel = "mart_logistica.embarques_mensual"
    assert propose.integrity(publicado, reconstruccion, [rel])[rel]["integridad"] == "INTACT"
    propose.simulate_incident(publicado, "INC-01")
    estado = propose.integrity(publicado, reconstruccion, [rel])[rel]
    assert estado == {"integridad": "DRIFTED", "filas_publicadas": 1, "filas_reconstruccion": 3}


def test_relacion_ausente_deja_la_integridad_desconocida(tmp_path):
    a, b = _base(tmp_path / "a.duckdb"), _base(tmp_path / "b.duckdb")
    assert propose.integrity(a, b, ["mart_logistica.no_existe"])["mart_logistica.no_existe"]["integridad"] == "UNKNOWN"
