"""Plataforma de ejecución: la guarda mínima de la propuesta del ADR 0006.

Detecta con qué sistema y arquitectura corre el proceso, la compara con la huella que `make setup`
deja en el entorno y, si no coinciden, explica el mecanismo en lugar de un traceback. Solo usa la
biblioteca estándar: corre antes de importar cualquier librería compilada (duckdb, dbt).

Un caso típico: en una Mac con Apple Silicon, si un programa x86_64 (p. ej. opencode instalado con
el Homebrew de Intel) lanza `dp`, el Python universal arranca como x86_64 y no puede cargar las
librerías arm64 que se instalaron en el setup.
"""

from __future__ import annotations

import json
import os
import platform
import struct
import subprocess
import sys
from pathlib import Path

ENTORNO_INVALIDO = 4  # código de salida (tabla de la propuesta del ADR 0007)
ARCH_ALIASES = {"amd64": "x86_64", "x64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "aarch64"}
SISTEMAS = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}
SENALES_DE_ARQUITECTURA = ("incompatible architecture", "mach-o", "wrong elf class", "exec format error",
                           "bad cpu type")
MACHO_CPU = {0x01000007: "x86_64", 0x0100000C: "arm64"}
ELF_MACHINE = {62: "x86_64", 183: "aarch64"}


def _sysctl(nombre: str) -> str | None:
    try:
        out = subprocess.run(["sysctl", "-n", nombre], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def sistema() -> str:
    return SISTEMAS.get(platform.system(), platform.system().lower())


def arquitectura() -> str:
    """Arquitectura del proceso (no la del hardware), con nombres canónicos por sistema."""
    arch = ARCH_ALIASES.get(platform.machine().lower(), platform.machine().lower())
    if sistema() == "linux" and arch == "arm64":
        arch = "aarch64"
    if sistema() == "macos" and arch == "aarch64":
        arch = "arm64"
    return arch


def traducido() -> bool:
    """El proceso corre traducido por Rosetta 2 (macOS)."""
    return sistema() == "macos" and _sysctl("sysctl.proc_translated") == "1"


def hardware_arm64() -> bool:
    if sistema() == "macos":
        return _sysctl("hw.optional.arm64") == "1"
    return arquitectura() in ("arm64", "aarch64")


def actual() -> dict:
    return {"etiqueta": f"{sistema()}-{arquitectura()}", "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
            "traducido": traducido()}


def ruta_huella() -> Path:
    return Path(sys.prefix) / "dp-plataforma.json"


def escribir_huella(ruta: Path | None = None) -> dict:
    huella = actual()
    (ruta or ruta_huella()).write_text(json.dumps(huella, indent=2) + "\n", encoding="utf-8")
    return huella


def _causa_y_remedio(estado: dict) -> str:
    if estado.get("traducido"):
        return ("Causa probable: lo lanzó un programa x86_64 que corre por Rosetta, p. ej. opencode instalado con "
                "el Homebrew de Intel (/usr/local). Remedio: instala la versión nativa (en Apple Silicon, Homebrew "
                "vive en /opt/homebrew) o corre dp desde una terminal nativa.")
    return ("Causa probable: el .venv se creó en otra máquina, con otra arquitectura o con otro Python. "
            "Remedio: vuelve a correr `make setup` desde una terminal nativa.")


def _cierre() -> str:
    return "Si eres un agente: no intentes repararlo (no corras `make setup`); reporta este mensaje a la persona."


def verificar(huella: dict | None = None, estado: dict | None = None) -> str | None:
    """Mensaje con el mecanismo si el proceso no corresponde al entorno instalado; None si sí corresponde.

    Sin huella no se bloquea: los entornos creados antes de esta guarda siguen funcionando.
    """
    if huella is None:
        ruta = ruta_huella()
        if not ruta.exists():
            return None
        try:
            huella = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    estado = estado or actual()
    como = estado["etiqueta"] + (" (traducido por Rosetta)" if estado.get("traducido") else "")
    if huella.get("etiqueta") != estado["etiqueta"]:
        return (f"dp no puede correr: el entorno se instaló para {huella.get('etiqueta')} y este proceso corre como "
                f"{como}, así que las librerías compiladas (duckdb) no cargarían. {_causa_y_remedio(estado)} {_cierre()}")
    if huella.get("python") != estado["python"]:
        return (f"dp no puede correr: el entorno se instaló con Python {huella.get('python')} y este proceso usa "
                f"Python {estado['python']}. Remedio: vuelve a correr `make setup`. {_cierre()}")
    return None


def explicar_importacion(exc: BaseException, estado: dict | None = None) -> str | None:
    """Traduce el error de cargar una librería compilada de otra arquitectura; None si es otro error."""
    texto = str(exc).lower()
    if not any(s in texto for s in SENALES_DE_ARQUITECTURA):
        return None
    estado = estado or actual()
    como = estado["etiqueta"] + (" (traducido por Rosetta)" if estado.get("traducido") else "")
    return (f"dp no puede correr: este proceso corre como {como} y las librerías compiladas del entorno (duckdb) "
            f"son de otra arquitectura. {_causa_y_remedio(estado)} {_cierre()}")


def arquitecturas_binario(ruta: Path) -> set | None:
    """Arquitecturas de un ejecutable Mach-O (simple o universal) o ELF; None si no se reconoce (p. ej. un script)."""
    try:
        with open(ruta, "rb") as fh:
            cabecera = fh.read(4096)
    except OSError:
        return None
    if len(cabecera) < 8:
        return None
    magic_be = struct.unpack(">I", cabecera[:4])[0]
    if magic_be in (0xCAFEBABE, 0xCAFEBABF):  # Mach-O universal (fat)
        n = struct.unpack(">I", cabecera[4:8])[0]
        tam = 20 if magic_be == 0xCAFEBABE else 32
        arquitecturas = set()
        for i in range(min(n, (len(cabecera) - 8) // tam)):
            cpu = struct.unpack(">I", cabecera[8 + i * tam: 12 + i * tam])[0]
            arquitecturas.add(MACHO_CPU.get(cpu, hex(cpu)))
        return arquitecturas
    if struct.unpack("<I", cabecera[:4])[0] in (0xFEEDFACF, 0xFEEDFACE):  # Mach-O simple
        cpu = struct.unpack("<I", cabecera[4:8])[0]
        return {MACHO_CPU.get(cpu, hex(cpu))}
    if cabecera[:4] == b"\x7fELF" and len(cabecera) >= 20:
        maquina = struct.unpack("<H" if cabecera[5] == 1 else ">H", cabecera[18:20])[0]
        return {ELF_MACHINE.get(maquina, str(maquina))}
    return None


def ejecutable_compatible(ruta: str) -> tuple:
    """(se puede lanzar, explicación). Un programa que correría traducido no se lanza: sus procesos hijos
    (`dp`) arrancarían con la arquitectura equivocada."""
    real = Path(os.path.realpath(ruta))
    arquitecturas = arquitecturas_binario(real)
    if arquitecturas is None:
        return True, f"no se pudo leer la arquitectura de {real} (¿un script?); se lanza sin verificar"
    nativa = "arm64" if sistema() == "macos" and hardware_arm64() else arquitectura()
    if nativa in arquitecturas:
        return True, f"{real} es nativo ({', '.join(sorted(arquitecturas))})"
    return False, (f"{real} es {', '.join(sorted(arquitecturas))} y esta máquina es {nativa}: correría traducido y los "
                   f"procesos que lance (`dp`) no podrían cargar las librerías del entorno. Instala la versión nativa "
                   f"(en Apple Silicon, Homebrew vive en /opt/homebrew).")


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--escribir-huella"]:
        huella = escribir_huella()
        print(f"plataforma del entorno: {huella['etiqueta']} · Python {huella['python']} ({ruta_huella()})")
        return 0
    print(json.dumps({**actual(), "hardware_arm64": hardware_arm64()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
