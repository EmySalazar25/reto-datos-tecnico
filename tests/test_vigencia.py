"""Una certificación guardada nunca se muestra como el estado actual si ya no lo describe.

El agente empieza siempre por `dp certify status`: si después de certificar hubo una
construcción, cambió el código o llegaron entregas, el estado viejo no debe parecer vigente.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_certify as tc

from dp import cli, evidence
from dp.certify import engine, render


def _repo(tmp_path: Path, monkeypatch) -> tuple:
    """Mini repo con código, una entrega y una certificación vigente de un producto sintético."""
    root = tmp_path / "repo"
    (root / "dbt" / "models").mkdir(parents=True)
    (root / "dbt" / "models" / "m.sql").write_text("select 1\n")
    (root / "dbt" / "dbt_project.yml").write_text("name: x\n")
    (root / "data" / "replica" / "carga_1").mkdir(parents=True)
    (root / "data" / "replica" / "carga_1" / "t.csv").write_text("a\n1\n")
    manifest = tc.base_manifest()
    ev = tc.write_evidence(root, manifest, tc.run_results(manifest))
    build = json.loads((ev / "build.json").read_text())
    (ev / "build.json").write_text(json.dumps({**build, "entradas": evidence.inputs_digest(root)}))
    cert = root / ".certification"
    render.write_outputs(engine.certify(ev, tc.POLICY, generated_at="2026-07-01T10:00:00Z"), cert)
    monkeypatch.setattr(cli, "CERT_DIR", cert)
    monkeypatch.setattr(cli.paths, "EVIDENCE_DIR", ev)
    monkeypatch.setattr(cli.paths, "ROOT", root)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return root, ev


def test_certificacion_vigente_se_muestra_tal_cual(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    assert cli.main(["certify", "status"]) == 0
    out = capsys.readouterr().out
    assert "CERTIFIED" in out and "DESACTUALIZADA" not in out


def test_construir_despues_de_certificar_la_desactualiza(tmp_path, monkeypatch, capsys):
    _, ev = _repo(tmp_path, monkeypatch)
    results = json.loads((ev / "run_results.json").read_text())
    next(r for r in results["results"] if r["unique_id"] == "test.estandar.m1")["status"] = "fail"
    (ev / "run_results.json").write_text(json.dumps(results))
    assert cli.main(["certify", "status"]) == 1
    out = capsys.readouterr().out
    assert "DESACTUALIZADA (última: CERTIFIED)" in out and "construcción" in out and "corre: dp certify run" in out


def test_cambiar_el_codigo_despues_de_construir_la_desactualiza(tmp_path, monkeypatch, capsys):
    root, _ = _repo(tmp_path, monkeypatch)
    (root / "dbt" / "models" / "m.sql").write_text("select 2\n")
    assert cli.main(["certify", "status"]) == 1
    out = capsys.readouterr().out
    assert "el código de dbt o las entregas cambiaron" in out and "dp build" in out


def test_una_entrega_nueva_sin_construir_la_desactualiza(tmp_path, monkeypatch, capsys):
    root, _ = _repo(tmp_path, monkeypatch)
    (root / "data" / "replica" / "carga_2").mkdir()
    (root / "data" / "replica" / "carga_2" / "t.csv").write_text("a\n2\n")
    assert cli.main(["certify", "status"]) == 1


def test_un_motor_distinto_la_desactualiza(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(engine, "ENGINE_VERSION", "9.9.9")
    assert cli.main(["certify", "status"]) == 1
    assert "el motor de certificación cambió" in capsys.readouterr().out


def test_una_construccion_sin_huella_de_entradas_no_se_da_por_vigente(tmp_path, monkeypatch, capsys):
    _, ev = _repo(tmp_path, monkeypatch)
    build = json.loads((ev / "build.json").read_text())
    del build["entradas"]
    (ev / "build.json").write_text(json.dumps(build))
    assert cli.main(["certify", "status"]) == 1


def test_la_vista_del_producto_no_presenta_el_estado_viejo(tmp_path, monkeypatch, capsys):
    root, _ = _repo(tmp_path, monkeypatch)
    (root / "dbt" / "models" / "m.sql").write_text("select 2\n")
    assert cli.main(["certify", "status", "disponibilidad_mensual"]) == 1
    out = capsys.readouterr().out
    assert "estado: DESACTUALIZADA" in out and "estado: CERTIFIED" not in out
    assert "siguiente: dp ingest && dp build && dp certify run" in out


def test_la_compuerta_no_pasa_con_una_certificacion_desactualizada(tmp_path, monkeypatch):
    root, _ = _repo(tmp_path, monkeypatch)
    assert cli.main(["certify", "gate"]) == 0
    (root / "dbt" / "models" / "m.sql").write_text("select 2\n")
    assert cli.main(["certify", "gate"]) == 1


def test_la_huella_de_entradas_ignora_artefactos_y_logs(tmp_path):
    root = tmp_path / "repo"
    (root / "dbt" / "macros").mkdir(parents=True)
    (root / "dbt" / "macros" / "m.sql").write_text("{% macro x() %}1{% endmacro %}\n")
    before = evidence.inputs_digest(root)
    (root / "dbt" / "target").mkdir()
    (root / "dbt" / "target" / "run_results.json").write_text("{}")
    (root / "dbt" / "logs").mkdir()
    (root / "dbt" / "logs" / "dbt.log").write_text("x")
    assert evidence.inputs_digest(root) == before
    (root / "dbt" / "macros" / "m.sql").write_text("{% macro x() %}2{% endmacro %}\n")
    assert evidence.inputs_digest(root) != before


def test_cada_construccion_registra_la_huella_de_sus_entradas(tmp_path):
    root = tmp_path / "repo"
    (root / "dbt" / "models").mkdir(parents=True)
    (root / "dbt" / "models" / "m.sql").write_text("select 1\n")
    ev = tmp_path / "evidencia"
    evidence.snapshot_build(ev, root / "dbt", tmp_path / "no-existe.duckdb", root, 0, "2026-07-01T09:00:00Z")
    assert json.loads((ev / "build.json").read_text())["entradas"] == evidence.inputs_digest(root)
