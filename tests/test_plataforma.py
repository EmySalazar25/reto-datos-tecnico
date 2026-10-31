"""Guarda de plataforma: un proceso con otra arquitectura que la del entorno recibe un mecanismo, no un traceback."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

from dp import entrada, plataforma


def _simular(monkeypatch, sistema: str, maquina: str, traducido: bool = False, hardware_arm64: bool = False):
    monkeypatch.setattr(plataforma.platform, "system", lambda: sistema)
    monkeypatch.setattr(plataforma.platform, "machine", lambda: maquina)
    sysctl = {"sysctl.proc_translated": "1" if traducido else "0", "hw.optional.arm64": "1" if hardware_arm64 else "0"}
    monkeypatch.setattr(plataforma, "_sysctl", lambda nombre: sysctl.get(nombre) if sistema == "Darwin" else None)


@pytest.mark.parametrize("sistema, maquina, etiqueta", [
    ("Darwin", "arm64", "macos-arm64"),
    ("Darwin", "x86_64", "macos-x86_64"),
    ("Linux", "x86_64", "linux-x86_64"),
    ("Linux", "aarch64", "linux-aarch64"),
    ("Linux", "arm64", "linux-aarch64"),
    ("Windows", "AMD64", "windows-x86_64"),
])
def test_etiqueta_canonica_por_sistema_y_arquitectura_del_proceso(monkeypatch, sistema, maquina, etiqueta):
    _simular(monkeypatch, sistema, maquina)
    assert plataforma.actual()["etiqueta"] == etiqueta


def test_rosetta_se_detecta(monkeypatch):
    _simular(monkeypatch, "Darwin", "x86_64", traducido=True, hardware_arm64=True)
    assert plataforma.traducido() and plataforma.hardware_arm64()


def test_proceso_traducido_frente_a_entorno_arm64_explica_el_mecanismo(monkeypatch):
    _simular(monkeypatch, "Darwin", "x86_64", traducido=True, hardware_arm64=True)
    mensaje = plataforma.verificar(huella={"etiqueta": "macos-arm64", "python": plataforma.actual()["python"]})
    assert "se instaló para macos-arm64" in mensaje and "macos-x86_64 (traducido por Rosetta)" in mensaje
    assert "Homebrew de Intel" in mensaje and "/opt/homebrew" in mensaje and "no corras `make setup`" in mensaje


def test_venv_de_otra_arquitectura_en_linux(monkeypatch):
    _simular(monkeypatch, "Linux", "aarch64")
    mensaje = plataforma.verificar(huella={"etiqueta": "linux-x86_64", "python": plataforma.actual()["python"]})
    assert "linux-aarch64" in mensaje and "make setup" in mensaje


def test_otro_python_que_el_del_setup(monkeypatch):
    _simular(monkeypatch, "Linux", "x86_64")
    mensaje = plataforma.verificar(huella={"etiqueta": "linux-x86_64", "python": "2.7"})
    assert "Python 2.7" in mensaje


def test_misma_plataforma_no_bloquea(monkeypatch):
    _simular(monkeypatch, "Darwin", "arm64", hardware_arm64=True)
    assert plataforma.verificar(huella=plataforma.actual()) is None


def test_sin_huella_no_bloquea_entornos_anteriores(monkeypatch, tmp_path):
    monkeypatch.setattr(plataforma, "ruta_huella", lambda: tmp_path / "no-existe.json")
    assert plataforma.verificar() is None


def test_la_huella_se_escribe_y_se_lee(monkeypatch, tmp_path):
    ruta = tmp_path / "dp-plataforma.json"
    monkeypatch.setattr(plataforma, "ruta_huella", lambda: ruta)
    escrita = plataforma.escribir_huella(ruta)
    assert json.loads(ruta.read_text()) == escrita and plataforma.verificar() is None


@pytest.mark.parametrize("error, reconoce", [
    ("dlopen(_duckdb.cpython-313-darwin.so): incompatible architecture (have 'arm64', need 'x86_64')", True),
    ("_duckdb.so: wrong ELF class: ELFCLASS32", True),
    ("No module named 'duckdb'", False),
])
def test_error_de_importacion_por_arquitectura(monkeypatch, error, reconoce):
    _simular(monkeypatch, "Darwin", "x86_64", traducido=True, hardware_arm64=True)
    mensaje = plataforma.explicar_importacion(ImportError(error))
    assert (mensaje is not None) == reconoce
    if reconoce:
        assert "traducido por Rosetta" in mensaje


def test_la_entrada_sale_con_codigo_4_sin_traceback(monkeypatch, capsys):
    monkeypatch.setattr(plataforma, "verificar", lambda: "dp no puede correr: mecanismo")
    assert entrada.main(["certify", "status"]) == 4
    assert "mecanismo" in capsys.readouterr().err


def test_la_entrada_traduce_el_error_de_importacion(monkeypatch, capsys):
    monkeypatch.setattr(plataforma, "verificar", lambda: None)

    def falla():
        raise ImportError("incompatible architecture (have 'arm64', need 'x86_64')")

    monkeypatch.setattr(entrada, "_cargar_cli", falla)
    assert entrada.main(["certify", "status"]) == 4
    assert "dp no puede correr" in capsys.readouterr().err


def test_la_entrada_no_oculta_otros_errores(monkeypatch):
    monkeypatch.setattr(plataforma, "verificar", lambda: None)

    def falla():
        raise ImportError("No module named 'dbt'")

    monkeypatch.setattr(entrada, "_cargar_cli", falla)
    with pytest.raises(ImportError):
        entrada.main([])


# --- Arquitectura de un ejecutable (para no lanzar un agente que correría traducido) ----------

def _macho(cpu: int) -> bytes:
    return struct.pack("<II", 0xFEEDFACF, cpu) + b"\0" * 24


def _universal(*cpus: int) -> bytes:
    cuerpo = b"".join(struct.pack(">IIIII", cpu, 0, 0, 0, 0) for cpu in cpus)
    return struct.pack(">II", 0xCAFEBABE, len(cpus)) + cuerpo


def _elf(maquina: int) -> bytes:
    return b"\x7fELF\x02\x01" + b"\0" * 12 + struct.pack("<H", maquina) + b"\0" * 10


@pytest.mark.parametrize("contenido, esperado", [
    (_macho(0x0100000C), {"arm64"}),
    (_macho(0x01000007), {"x86_64"}),
    (_universal(0x01000007, 0x0100000C), {"x86_64", "arm64"}),
    (_elf(62), {"x86_64"}),
    (_elf(183), {"aarch64"}),
    (b"#!/usr/bin/env node\nrequire('x')\n", None),
])
def test_arquitecturas_de_un_ejecutable(tmp_path, contenido, esperado):
    ruta = tmp_path / "bin"
    ruta.write_bytes(contenido)
    assert plataforma.arquitecturas_binario(ruta) == esperado


def test_lee_el_ejecutable_real_de_python():
    arquitecturas = plataforma.arquitecturas_binario(Path(sys.executable).resolve())
    if arquitecturas is not None:  # Windows u otro formato: no aplica
        assert plataforma.arquitectura() in arquitecturas


def test_opencode_de_intel_en_apple_silicon_no_se_lanza(monkeypatch, tmp_path):
    _simular(monkeypatch, "Darwin", "arm64", hardware_arm64=True)
    binario = tmp_path / "opencode"
    binario.write_bytes(_macho(0x01000007))
    puede, razon = plataforma.ejecutable_compatible(str(binario))
    assert not puede and "x86_64" in razon and "/opt/homebrew" in razon


@pytest.mark.parametrize("contenido", [_macho(0x0100000C), _universal(0x01000007, 0x0100000C), b"#!/bin/sh\n"])
def test_opencode_nativo_universal_o_script_se_lanza(monkeypatch, tmp_path, contenido):
    _simular(monkeypatch, "Darwin", "arm64", hardware_arm64=True)
    binario = tmp_path / "opencode"
    binario.write_bytes(contenido)
    assert plataforma.ejecutable_compatible(str(binario))[0]


def test_sigue_enlaces_simbolicos(monkeypatch, tmp_path):
    _simular(monkeypatch, "Darwin", "arm64", hardware_arm64=True)
    real = tmp_path / "Cellar" / "opencode"
    real.parent.mkdir()
    real.write_bytes(_macho(0x01000007))
    enlace = tmp_path / "opencode"
    enlace.symlink_to(real)
    assert not plataforma.ejecutable_compatible(str(enlace))[0]
