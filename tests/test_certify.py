"""Pruebas del Certification Engine con un dominio sintético distinto a Logística.

Si el engine certifica un producto de mantenimiento sin cambiar código, el estándar generaliza:
todo lo que evalúa sale de metadata, tests, artifacts y la política.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from dp.certify import engine
from dp.certify.checks import CheckResult

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "standard" / "policy.yml"

SRC = "source.estandar.landing_mto.equipos"
STG = "model.estandar.stg_mto__equipos"
PROD = "model.estandar.disponibilidad_mensual"
UT = "unit_test.estandar.disponibilidad_mensual.ut_m1"


def base_manifest() -> dict:
    def test(uid, name, deps, tags=(), meta=None, attached=None, generic=None, kwargs=None, severity="ERROR"):
        node = {
            "resource_type": "test", "unique_id": uid, "name": name, "tags": list(tags),
            "config": {"tags": list(tags), "meta": meta or {}, "severity": severity},
            "depends_on": {"nodes": deps}, "attached_node": attached,
        }
        if generic:
            node["test_metadata"] = {"name": generic, "kwargs": kwargs or {}}
        return node

    nodes = {
        STG: {"resource_type": "model", "unique_id": STG, "name": "stg_mto__equipos",
              "fqn": ["estandar", "staging", "mto", "stg_mto__equipos"], "config": {}, "meta": {}, "raw_code": "select 1"},
        PROD: {
            "resource_type": "model", "unique_id": PROD, "name": "disponibilidad_mensual", "access": "public",
            "group": "mantenimiento", "schema": "mart_mantenimiento", "fqn": ["estandar", "mart", "mantenimiento", "disponibilidad_mensual"],
            "description": "Horas disponibles por equipo y mes.",
            "config": {"contract": {"enforced": True}},
            "meta": {
                "grain": ["anio_mes", "cla_equipo"], "primary_key": ["anio_mes", "cla_equipo"], "contract_version": 1,
                "criticality": "media", "technical_owner": "ingenieria_de_datos",
                "sla": {"freshness_hours": 24}, "performance": {"partition_exempt_reason": "agregado mensual"},
                "business_rules": [{"id": "M1", "description": "Disponibilidad = horas operables / horas calendario."}],
            },
            "columns": {
                "anio_mes": {"data_type": "varchar", "description": "Mes."},
                "cla_equipo": {"data_type": "integer", "description": "Equipo."},
            },
            "raw_code": "select anio_mes, cla_equipo from x",
        },
        "test.estandar.grano": test("test.estandar.grano", "grano", [PROD], attached=PROD, generic="combinacion_unica",
                                    kwargs={"columnas": ["anio_mes", "cla_equipo"]}),
        "test.estandar.not_null": test("test.estandar.not_null", "not_null", [PROD], attached=PROD, generic="not_null"),
        "test.estandar.dedup": test("test.estandar.dedup", "dedup", [STG], tags=["engineering"], attached=STG, generic="unique"),
        "test.estandar.m1": test("test.estandar.m1", "m1", [STG, PROD], tags=["business"], meta={"rule": "M1"}),
    }
    return {
        "nodes": nodes,
        "sources": {SRC: {"unique_id": SRC, "schema": "landing_mto", "name": "equipos",
                          "freshness": {"warn_after": {"count": 24, "period": "hour"}, "error_after": {"count": 48, "period": "hour"}}}},
        "parent_map": {PROD: [STG], STG: [SRC], SRC: []},
        "child_map": {SRC: [STG], STG: [PROD], PROD: []},
        "groups": {"group.estandar.mantenimiento": {"name": "mantenimiento", "owner": {"name": "Dirección de Mantenimiento"}}},
        "exposures": {"exposure.estandar.tablero_mto": {"depends_on": {"nodes": [PROD]}}},
        "unit_tests": {UT: {"resource_type": "unit_test", "unique_id": UT, "name": "ut_m1",
                            "config": {"tags": ["business"], "meta": {"rule": "M1"}}, "depends_on": {"nodes": [PROD]}}},
    }


def run_results(manifest: dict, overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    results = []
    for uid in list(manifest["nodes"]) + list(manifest["unit_tests"]):
        node = manifest["nodes"].get(uid) or manifest["unit_tests"][uid]
        status = "success" if node["resource_type"] == "model" else "pass"
        r = {"unique_id": uid, "status": overrides.get(uid, status), "failures": 0, "message": None, "execution_time": 0.1}
        if uid == PROD:
            r["timing"] = [{"name": "execute", "completed_at": "2026-07-01T09:00:00Z"}]
        results.append(r)
    return {"results": results}


REGISTRY = [{"id_entrega": "carga_1", "archivo": "equipos.csv", "tabla_destino": "landing_mto.equipos", "estado": "cargada",
             "filas": 10, "max_extraido_en": "2026-07-01T08:00:00.000Z", "ingerido_en": "2026-07-01 08:30:00",
             "columnas_faltantes": [], "columnas_nuevas": []}]


def write_evidence(tmp: Path, manifest: dict, results: dict, ci_extras: bool = False) -> Path:
    ev = tmp / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "manifest.json").write_text(json.dumps(manifest))
    (ev / "run_results.json").write_text(json.dumps(results))
    (ev / "entregas.json").write_text(json.dumps(REGISTRY))
    (ev / "build.json").write_text(json.dumps({"commit": "abc1234", "codigo_salida": 0, "fin": "2026-07-01T09:00:00Z"}))
    if ci_extras:
        (ev / "idempotencia.json").write_text(json.dumps({"status": "PASS", "tablas": [{"tabla": "x"}], "tablas_con_cambios": []}))
        (ev / "chaos_resultados.json").write_text(json.dumps({"escenarios": [{"id": "CH-M1", "reglas": ["M1"], "estado": "DETECTADO"}]}))
    return ev


def certify(tmp: Path, manifest=None, results=None, ci_extras=False, **kwargs) -> dict:
    manifest = manifest or base_manifest()
    results = results or run_results(manifest)
    ev = write_evidence(tmp, manifest, results, ci_extras)
    out = engine.certify(ev, POLICY, generated_at="2026-07-01T10:00:00Z", **kwargs)
    (prod,) = out["products"]
    return prod


def test_segundo_dominio_certifica_sin_codigo_especifico(tmp_path):
    prod = certify(tmp_path)
    assert prod["status"] == "CERTIFIED", prod["reasons"]
    assert prod["product"]["domain"] == "mantenimiento"
    assert prod["product"]["owner"] == "Dirección de Mantenimiento"


def test_evaluacion_es_determinista(tmp_path):
    a = certify(tmp_path / "a")
    b = certify(tmp_path / "b")
    assert a["checks"] == b["checks"] and a["status"] == b["status"]
    assert a["evaluation"]["policy_digest"] == b["evaluation"]["policy_digest"]


def test_producto_sin_dueno_no_se_certifica(tmp_path):
    m = base_manifest()
    m["groups"]["group.estandar.mantenimiento"]["owner"] = {}
    prod = certify(tmp_path, manifest=m)
    assert prod["status"] == "NOT_CERTIFIED" and "GOV-01" in prod["reasons"]


def test_grano_declarado_sin_test_no_cuenta(tmp_path):
    m = base_manifest()
    del m["nodes"]["test.estandar.grano"]
    prod = certify(tmp_path, manifest=m)
    # La ausencia del test es una falla de diseño (gobernanza); TST-03 también lo reporta.
    assert prod["status"] == "NOT_CERTIFIED" and "GOV-03" in prod["reasons"]
    assert next(c for c in prod["checks"] if c["id"] == "TST-03")["status"] == "FAIL"


def test_regla_sin_unit_test_no_se_certifica(tmp_path):
    m = base_manifest()
    m["unit_tests"] = {}
    prod = certify(tmp_path, manifest=m)
    assert prod["status"] == "NOT_CERTIFIED" and "GOV-05" in prod["reasons"]


def test_regla_violada_por_los_datos_degrada_en_operacion(tmp_path):
    m = base_manifest()
    prod = certify(tmp_path, manifest=m, results=run_results(m, {"test.estandar.m1": "fail"}))
    assert prod["status"] == "DEGRADED" and prod["health"] == "FAILED" and "TST-05" in prod["reasons"]


def test_la_misma_falla_en_ci_no_certifica_la_version(tmp_path):
    m = base_manifest()
    prod = certify(tmp_path, manifest=m, results=run_results(m, {"test.estandar.m1": "fail"}), ci_extras=True,
                   context="ci", base_manifest=None)
    assert prod["status"] == "NOT_CERTIFIED" and "TST-05" in prod["reasons"]


def test_unit_test_que_falla_no_certifica_aunque_sea_operacion(tmp_path):
    m = base_manifest()
    prod = certify(tmp_path, manifest=m, results=run_results(m, {UT: "fail"}))
    assert prod["status"] == "NOT_CERTIFIED" and "TST-06" in prod["reasons"]


def test_frescura_fuera_de_umbral_es_stale(tmp_path):
    prod = certify(tmp_path, as_of="2026-07-04T08:00:00Z")
    assert prod["status"] == "DEGRADED" and prod["health"] == "STALE"
    assert prod["evaluation"]["clock"] == "explicit"


def test_metricas_de_bigquery_no_se_simulan_en_local(tmp_path):
    prod = certify(tmp_path)
    build = {m["name"]: m for m in prod["metrics"]["build"]}
    assert build["duration_ms"]["provenance"] == "measured"
    for name in ("bytes_processed", "bytes_billed", "slot_ms", "estimated_cost"):
        assert build[name]["provenance"] == "not_available" and build[name]["value"] is None


def _base_file(tmp: Path, manifest: dict) -> Path:
    path = tmp / "base_manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_bajar_severidad_de_un_test_requiere_aprobacion(tmp_path):
    base = base_manifest()
    current = copy.deepcopy(base)
    current["nodes"]["test.estandar.m1"]["config"]["severity"] = "warn"
    kwargs = dict(context="ci", ci_extras=True, base_manifest=_base_file(tmp_path, base), base_policy=POLICY)
    prod = certify(tmp_path, manifest=current, **kwargs)
    gov7 = next(c for c in prod["checks"] if c["id"] == "GOV-07")
    assert gov7["status"] == "FAIL" and gov7["evidence"][0]["tipo"] == "severidad_rebajada"
    approved = certify(tmp_path / "ok", manifest=current, approved_by="revisora", **kwargs)
    assert next(c for c in approved["checks"] if c["id"] == "GOV-07")["status"] == "PASS"


def test_eliminar_un_test_de_regla_requiere_aprobacion(tmp_path):
    base = base_manifest()
    current = copy.deepcopy(base)
    del current["nodes"]["test.estandar.m1"]
    prod = certify(tmp_path, manifest=current, context="ci", ci_extras=True,
                   base_manifest=_base_file(tmp_path, base), base_policy=POLICY)
    gov7 = next(c for c in prod["checks"] if c["id"] == "GOV-07")
    assert gov7["status"] == "FAIL" and any(e["tipo"] == "test_eliminado" for e in gov7["evidence"])


def test_cambio_de_politica_requiere_aprobacion(tmp_path):
    other_policy = tmp_path / "policy_base.yml"
    other_policy.write_text("version: 0\n")
    prod = certify(tmp_path, context="ci", ci_extras=True,
                   base_manifest=_base_file(tmp_path, base_manifest()), base_policy=other_policy)
    gov7 = next(c for c in prod["checks"] if c["id"] == "GOV-07")
    assert gov7["status"] == "FAIL" and gov7["evidence"][0]["tipo"] == "politica_modificada"


def test_romper_contrato_requiere_aprobacion(tmp_path):
    base = base_manifest()
    current = copy.deepcopy(base)
    current["nodes"][PROD]["columns"]["cla_equipo"]["data_type"] = "varchar"
    prod = certify(tmp_path, manifest=current, context="ci", ci_extras=True,
                   base_manifest=_base_file(tmp_path, base), base_policy=POLICY)
    gov7 = next(c for c in prod["checks"] if c["id"] == "GOV-07")
    assert gov7["status"] == "FAIL" and gov7["evidence"][0]["tipos_cambiados"] == ["cla_equipo"]


@pytest.mark.parametrize(
    "checks, expected",
    [
        ([("TST-06", "design", "FAIL"), ("OBS-01", "runtime", "FAIL")], ("NOT_CERTIFIED", "STALE")),
        ([("TST-06", "design", "PASS"), ("OBS-01", "runtime", "FAIL")], ("DEGRADED", "STALE")),
        ([("TST-05", "runtime", "FAIL"), ("OBS-01", "runtime", "FAIL")], ("DEGRADED", "FAILED")),
        ([("GOV-06", "design", "WARN"), ("OBS-01", "runtime", "PASS")], ("CERTIFIED_WITH_WARNINGS", "HEALTHY")),
        ([("OBS-03", "runtime", "WARN")], ("CERTIFIED_WITH_WARNINGS", "AT_RISK")),
        ([("OBS-02", "runtime", "UNKNOWN")], ("DEGRADED", "UNKNOWN")),
        ([("TST-08", "design", "NOT_APPLICABLE"), ("OBS-01", "runtime", "PASS")], ("CERTIFIED", "HEALTHY")),
    ],
)
def test_precedencia_de_estados(checks, expected):
    results = [CheckResult(id=i, dimension="x", title="x", phase=ph, status=st, summary="") for i, ph, st in checks]
    status, health, _ = engine.aggregate(results)
    assert (status, health) == expected
