"""Pruebas del Certification Engine con un dominio sintético distinto a Logística.

Si el engine certifica un producto de mantenimiento sin cambiar código, el estándar generaliza:
todo lo que evalúa sale de metadata, tests, artifacts y la política.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from dp.certify import cambios, engine
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


CODEOWNERS = "/standard/ @duena\n/src/dp/certify/ @duena\n/.github/ @duena\n/opencode.json @duena\n"


def _raw_diff(*entries) -> bytes:
    """Formato de `git diff --raw -z --no-abbrev --no-renames`: (archivo, blob antes, blob después)."""
    return b"".join(f":100644 100644 {a} {b} M".encode() + b"\0" + path.encode() + b"\0" for path, a, b in entries)


def _gov_kwargs(tmp: Path, base: dict, diff: bytes = b"", base_policy: Path = POLICY) -> dict:
    """Lo que el CI le pasa a la certificación: versión base, CODEOWNERS de la base y archivos cambiados."""
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "CODEOWNERS").write_text(CODEOWNERS)
    (tmp / "cambios.diff").write_bytes(diff)
    return dict(context="ci", ci_extras=True, base_manifest=_base_file(tmp, base), base_policy=base_policy,
                base_codeowners=tmp / "CODEOWNERS", changed_files=tmp / "cambios.diff")


def _gov7(prod: dict) -> dict:
    return next(c for c in prod["checks"] if c["id"] == "GOV-07")


def _lower_severity(manifest: dict, test_id: str = "test.estandar.m1") -> dict:
    current = copy.deepcopy(manifest)
    current["nodes"][test_id]["config"]["severity"] = "warn"
    return current


def test_bajar_severidad_de_un_test_requiere_aprobacion(tmp_path):
    base = base_manifest()
    current = _lower_severity(base)
    kwargs = _gov_kwargs(tmp_path, base)
    prod = certify(tmp_path, manifest=current, **kwargs)
    assert _gov7(prod)["status"] == "FAIL" and _gov7(prod)["evidence"][0]["tipo"] == "severidad_rebajada"
    assert prod["status"] == "NOT_CERTIFIED" and prod["reasons"] == ["GOV-07"]
    huella = prod["evaluation"]["cambios_gobernados"]["huella"]
    approved = certify(tmp_path / "ok", manifest=current, approval={"huella": huella, "aprobado_por": "revisora"}, **kwargs)
    assert _gov7(approved)["status"] == "PASS" and "revisora" in _gov7(approved)["summary"]
    assert approved["status"] != "NOT_CERTIFIED"


def test_eliminar_un_test_de_regla_requiere_aprobacion(tmp_path):
    base = base_manifest()
    current = copy.deepcopy(base)
    del current["nodes"]["test.estandar.m1"]
    prod = certify(tmp_path, manifest=current, **_gov_kwargs(tmp_path, base))
    assert _gov7(prod)["status"] == "FAIL" and any(e["tipo"] == "test_eliminado" for e in _gov7(prod)["evidence"])


def test_cambio_de_politica_requiere_aprobacion(tmp_path):
    other_policy = tmp_path / "policy_base.yml"
    other_policy.write_text("version: 0\n")
    prod = certify(tmp_path, **_gov_kwargs(tmp_path, base_manifest(), base_policy=other_policy))
    assert _gov7(prod)["status"] == "FAIL" and _gov7(prod)["evidence"][0]["tipo"] == "politica_modificada"


def test_romper_contrato_requiere_aprobacion(tmp_path):
    base = base_manifest()
    current = copy.deepcopy(base)
    current["nodes"][PROD]["columns"]["cla_equipo"]["data_type"] = "varchar"
    prod = certify(tmp_path, manifest=current, **_gov_kwargs(tmp_path, base))
    change = _gov7(prod)["evidence"][0]
    assert _gov7(prod)["status"] == "FAIL" and change["tipos_cambiados"] == ["cla_equipo"]
    assert change["tipos"] == {"cla_equipo": ["integer", "varchar"]}


def test_aprobacion_de_otro_cambio_no_vale(tmp_path):
    """Aprobado bajar la severidad de M1; después también se baja la del grano: la aprobación ya no aplica."""
    base = base_manifest()
    first = _lower_severity(base)
    kwargs = _gov_kwargs(tmp_path, base)
    huella = certify(tmp_path / "a", manifest=first, **kwargs)["evaluation"]["cambios_gobernados"]["huella"]
    second = _lower_severity(first, "test.estandar.grano")
    prod = certify(tmp_path / "b", manifest=second, approval={"huella": huella, "aprobado_por": "revisora"}, **kwargs)
    assert _gov7(prod)["status"] == "FAIL" and "otro cambio" in _gov7(prod)["summary"]
    assert prod["status"] == "NOT_CERTIFIED"


def test_aprobacion_sin_huella_no_vale(tmp_path):
    base = base_manifest()
    prod = certify(tmp_path, manifest=_lower_severity(base), approval={"aprobado_por": "revisora"},
                   **_gov_kwargs(tmp_path, base))
    assert _gov7(prod)["status"] == "FAIL"


def test_cambio_de_tipo_distinto_tiene_otra_huella(tmp_path):
    base = base_manifest()
    huellas = []
    for i, new_type in enumerate(["varchar", "double"]):
        current = copy.deepcopy(base)
        current["nodes"][PROD]["columns"]["cla_equipo"]["data_type"] = new_type
        prod = certify(tmp_path / str(i), manifest=current, **_gov_kwargs(tmp_path / str(i), base))
        huellas.append(prod["evaluation"]["cambios_gobernados"]["huella"])
    assert huellas[0] != huellas[1]


def test_la_huella_no_depende_de_la_base_ni_del_orden(tmp_path):
    """El PR (base = main al abrirlo) y el merge (base = main anterior) del mismo cambio dan la misma huella."""
    base_a = base_manifest()
    base_b = copy.deepcopy(base_a)
    base_b["nodes"] = dict(reversed(list(base_b["nodes"].items())))
    base_b["nodes"]["model.estandar.otro"] = {"resource_type": "model", "unique_id": "model.estandar.otro", "name": "otro",
                                              "config": {}, "meta": {}, "raw_code": "select 2"}
    a = certify(tmp_path / "a", manifest=_lower_severity(base_a), **_gov_kwargs(tmp_path / "a", base_a))
    b = certify(tmp_path / "b", manifest=_lower_severity(base_b), **_gov_kwargs(tmp_path / "b", base_b))
    assert a["evaluation"]["cambios_gobernados"]["huella"] == b["evaluation"]["cambios_gobernados"]["huella"]


def test_ruta_protegida_de_codeowners_requiere_aprobacion(tmp_path):
    base = base_manifest()
    diff = _raw_diff(("src/dp/certify/checks.py", "a" * 40, "b" * 40), ("dbt/models/mart/x.sql", "c" * 40, "d" * 40))
    prod = certify(tmp_path, manifest=copy.deepcopy(base), **_gov_kwargs(tmp_path, base, diff))
    gov7 = _gov7(prod)
    assert gov7["status"] == "FAIL"
    assert gov7["evidence"] == [{"tipo": "ruta_protegida", "archivo": "src/dp/certify/checks.py",
                                 "antes": "a" * 40, "despues": "b" * 40}]


def test_modificar_una_ruta_protegida_despues_de_aprobar_invalida_la_aprobacion(tmp_path):
    base = base_manifest()
    approved_diff = _raw_diff((".github/workflows/ci.yml", "a" * 40, "b" * 40))
    kwargs = _gov_kwargs(tmp_path / "a", base, approved_diff)
    huella = certify(tmp_path / "a", manifest=copy.deepcopy(base), **kwargs)["evaluation"]["cambios_gobernados"]["huella"]
    approval = {"huella": huella, "aprobado_por": "revisora"}
    same = certify(tmp_path / "a2", manifest=copy.deepcopy(base), approval=approval, **kwargs)
    assert _gov7(same)["status"] == "PASS"
    edited = _raw_diff((".github/workflows/ci.yml", "a" * 40, "e" * 40))
    prod = certify(tmp_path / "b", manifest=copy.deepcopy(base), approval=approval,
                   **_gov_kwargs(tmp_path / "b", base, edited))
    assert _gov7(prod)["status"] == "FAIL" and "otro cambio" in _gov7(prod)["summary"]


def test_sin_lista_de_archivos_cambiados_gov07_queda_sin_evidencia(tmp_path):
    base = base_manifest()
    kwargs = _gov_kwargs(tmp_path, base)
    del kwargs["changed_files"]
    prod = certify(tmp_path, manifest=_lower_severity(base), **kwargs)
    assert _gov7(prod)["status"] == "UNKNOWN" and prod["status"] == "NOT_CERTIFIED"


def test_aprobacion_no_tapa_otras_fallas(tmp_path):
    base = base_manifest()
    current = _lower_severity(base)
    current["groups"]["group.estandar.mantenimiento"]["owner"] = {}
    kwargs = _gov_kwargs(tmp_path, base)
    huella = certify(tmp_path / "a", manifest=current, **kwargs)["evaluation"]["cambios_gobernados"]["huella"]
    prod = certify(tmp_path / "b", manifest=current, approval={"huella": huella, "aprobado_por": "revisora"}, **kwargs)
    assert _gov7(prod)["status"] == "PASS" and prod["status"] == "NOT_CERTIFIED" and "GOV-01" in prod["reasons"]


@pytest.mark.parametrize(
    "path, protected",
    [
        ("standard/policy.yml", True),
        ("standard/chaos/catalogo.yml", True),
        ("src/dp/certify/checks.py", True),
        (".github/workflows/ci.yml", True),
        (".github/CODEOWNERS", True),
        ("opencode.json", True),
        ("AGENTS.md", True),
        (".agents/skills/diagnosticar-falla/SKILL.md", True),
        ("src/dp/cli.py", False),
        ("dbt/models/mart/logistica/embarques_mensual.sql", False),
        ("docs/opencode.json", False),
    ],
)
def test_rutas_protegidas_del_codeowners_del_repo(path, protected):
    patterns = cambios.codeowners_patterns((ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8"))
    assert cambios.is_protected(path, patterns) is protected


def test_lee_el_diff_real_de_git(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout

    git("init", "-q")
    git("config", "user.email", "prueba@example.invalid")
    git("config", "user.name", "prueba")
    (repo / "opencode.json").write_text("{}\n")
    (repo / "con espacio.txt").write_text("a\n")
    git("add", ".")
    git("commit", "-qm", "base")
    (repo / "opencode.json").write_text('{"x": 1}\n')
    (repo / "con espacio.txt").unlink()
    (repo / "nuevo.sql").write_text("select 1\n")
    git("add", "-A")
    git("commit", "-qm", "cambio")
    entries = cambios.parse_raw_diff(git("diff", "--raw", "-z", "--no-abbrev", "--no-renames", "HEAD~1", "HEAD"))
    by_path = {e["archivo"]: e for e in entries}
    assert set(by_path) == {"opencode.json", "con espacio.txt", "nuevo.sql"}
    assert by_path["con espacio.txt"]["estado"] == "D" and set(by_path["con espacio.txt"]["despues"]) == {"0"}
    assert by_path["nuevo.sql"]["estado"] == "A" and set(by_path["nuevo.sql"]["antes"]) == {"0"}
    assert len(by_path["opencode.json"]["antes"]) == 40 and by_path["opencode.json"]["antes"] != by_path["opencode.json"]["despues"]


def test_la_cli_ya_no_acepta_un_aprobador_como_texto():
    from dp.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["certify", "run", "--aprobado-por", "alguien"])


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
        # Nodos omitidos por una falla de datos: la versión no está demostrada rota.
        ([("TST-06", "design", "UNKNOWN"), ("TST-01", "runtime", "FAIL")], ("DEGRADED", "FAILED")),
        # Sin falla de datos que lo explique, la falta de evidencia de diseño no certifica.
        ([("TST-06", "design", "UNKNOWN"), ("TST-01", "runtime", "PASS")], ("NOT_CERTIFIED", "HEALTHY")),
    ],
)
def test_precedencia_de_estados(checks, expected):
    results = [CheckResult(id=i, dimension="x", title="x", phase=ph, status=st, summary="") for i, ph, st in checks]
    status, health, _ = engine.aggregate(results)
    assert (status, health) == expected


def test_fuente_sin_entrega_reciente_es_advertencia_y_replica_detenida_es_stale(tmp_path):
    """En CDC una tabla sin cambios puede no venir en la entrega: no es una falla del producto."""
    m = base_manifest()
    src2 = "source.estandar.landing_mto.turnos"
    m["sources"][src2] = {**m["sources"][SRC], "unique_id": src2, "name": "turnos"}
    m["parent_map"][STG] = [SRC, src2]
    registry = REGISTRY + [{**REGISTRY[0], "archivo": "turnos.csv", "tabla_destino": "landing_mto.turnos",
                            "max_extraido_en": "2026-06-28T08:00:00.000Z"}]
    ev = write_evidence(tmp_path, m, run_results(m))
    (ev / "entregas.json").write_text(json.dumps(registry))
    out = engine.certify(ev, POLICY, generated_at="2026-07-01T10:00:00Z")
    (prod,) = out["products"]
    obs1 = next(c for c in prod["checks"] if c["id"] == "OBS-01")
    assert obs1["status"] == "WARN" and prod["status"] == "CERTIFIED_WITH_WARNINGS"
    stale = engine.certify(ev, POLICY, as_of="2026-07-04T09:00:00Z", generated_at="2026-07-04T10:00:00Z")["products"][0]
    assert stale["health"] == "STALE" and stale["status"] == "DEGRADED"
