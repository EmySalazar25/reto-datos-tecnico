"""Punto de entrada de `dp`: verifica la plataforma antes de cargar las librerías compiladas.

`dp.cli` importa (vía `dp.evidence`) duckdb al cargarse; si el proceso corre con otra
arquitectura que la del entorno, el error sería un traceback. Aquí se convierte en un mensaje
con mecanismo y el código 4 (entorno inválido).
"""

from __future__ import annotations

import sys

from dp import plataforma


def _cargar_cli():
    from dp import cli

    return cli


def main(argv: list | None = None) -> int:
    mensaje = plataforma.verificar()
    if mensaje:
        print(mensaje, file=sys.stderr)
        return plataforma.ENTORNO_INVALIDO
    try:
        cli = _cargar_cli()
    except ImportError as exc:
        mensaje = plataforma.explicar_importacion(exc)
        if mensaje is None:
            raise
        print(mensaje, file=sys.stderr)
        return plataforma.ENTORNO_INVALIDO
    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
