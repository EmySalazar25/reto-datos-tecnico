"""`make chaos` nunca deja la falla inyectada, pase lo que pase con el agente."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from dp import chaos, cli, plataforma

ORIGINAL = "select sum(costo) from viajes\n"
ROTO = "select sum(costo) from viajes join partidas  -- roto\n"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """Escenario de código sobre un archivo temporal; la certificación depende de su contenido real."""
    modelo = tmp_path / "dbt" / "models" / "mart.sql"
    modelo.parent.mkdir(parents=True)
    modelo.write_text(ORIGINAL)
    monkeypatch.setattr(cli.paths, "ROOT", tmp_path)
    monkeypatch.setattr(chaos, "code_target", lambda scenario_id: modelo)
    monkeypatch.setattr(chaos, "inject", lambda scenario_id: modelo.write_text(ROTO) and "inyectado")
    monkeypatch.setattr(chaos, "restore", lambda scenario_id: pytest.fail("un escenario de código se restaura desde la copia"))
    monkeypatch.setattr(cli, "run_build", lambda *a, **k: 0)
    monkeypatch.setattr(cli, "_certify_quiet",
                        lambda context="run": {"embarques_mensual": "NOT_CERTIFIED" if "roto" in modelo.read_text() else "CERTIFIED"})
    monkeypatch.setattr(cli, "render_status", lambda producto: "")
    monkeypatch.setattr(cli, "cmd_diagnose", lambda args: 0)
    monkeypatch.setattr(shutil, "which", lambda nombre: "/fake/opencode")
    monkeypatch.setattr(plataforma, "ejecutable_compatible", lambda ruta: (True, "nativo"))
    monkeypatch.delenv("DP_AGENTE", raising=False)
    monkeypatch.delenv("DP_AGENTE_MODELO", raising=False)
    return modelo


def _agente(monkeypatch, efecto):
    llamadas = []

    def call(cmd, cwd=None):
        llamadas.append(cmd)
        return efecto()

    monkeypatch.setattr(subprocess, "call", call)
    return llamadas


def test_agente_que_no_corrige_se_restaura(demo, monkeypatch, capsys):
    _agente(monkeypatch, lambda: 1)  # cuota agotada, modelo caído…
    assert cli.chaos_demo("CH-01") == 0
    assert demo.read_text() == ORIGINAL
    out = capsys.readouterr().out
    assert "el agente no recuperó la certificación" in out and "RECUPERADO" in out


def test_agente_que_corrige_deja_su_cambio_y_lo_avisa(demo, monkeypatch, capsys):
    _agente(monkeypatch, lambda: demo.write_text("select sum(costo) from viajes  -- corregido\n") and 0)
    assert cli.chaos_demo("CH-01") == 0
    assert "corregido" in demo.read_text()
    assert "git diff" in capsys.readouterr().out


def test_opencode_que_correria_traducido_no_se_lanza(demo, monkeypatch, capsys):
    llamadas = _agente(monkeypatch, lambda: pytest.fail("no debía lanzarse"))
    monkeypatch.setattr(plataforma, "ejecutable_compatible", lambda ruta: (False, "es x86_64 y esta máquina es arm64"))
    assert cli.chaos_demo("CH-01") == 0
    assert llamadas == [] and demo.read_text() == ORIGINAL
    assert "no se lanza el agente: es x86_64" in capsys.readouterr().out


def test_agente_que_no_arranca_se_restaura(demo, monkeypatch):
    def no_arranca():
        raise OSError("Bad CPU type in executable")

    _agente(monkeypatch, no_arranca)
    assert cli.chaos_demo("CH-01") == 0
    assert demo.read_text() == ORIGINAL


def test_interrumpir_la_demo_no_deja_la_falla(demo, monkeypatch):
    def interrupcion():
        raise KeyboardInterrupt

    _agente(monkeypatch, interrupcion)
    with pytest.raises(KeyboardInterrupt):
        cli.chaos_demo("CH-01")
    assert demo.read_text() == ORIGINAL


def test_sin_opencode_se_restaura_como_antes(demo, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda nombre: None)
    assert cli.chaos_demo("CH-01") == 0
    assert demo.read_text() == ORIGINAL
    assert "opencode no está instalado" in capsys.readouterr().out
