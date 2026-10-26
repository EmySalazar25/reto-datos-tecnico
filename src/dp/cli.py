"""Punto de entrada `dp`. Cada subcomando devuelve una salida corta, útil para personas y para el agente."""

from __future__ import annotations

import argparse
import sys

from dp import dbt_runner, ingest, paths
from dp.sources import load_declared_sources


def cmd_ingest(args: argparse.Namespace) -> int:
    declared = load_declared_sources(paths.DBT_DIR)
    results = ingest.ingest_all(paths.DUCKDB_PATH, paths.DATA_DIR, declared, only=args.entrega)
    if not results:
        print(f"sin entregas en {paths.DATA_DIR}")
        return 0
    for r in results:
        print(r.line())
    cargadas = sum(r.estado == "cargada" for r in results)
    rechazadas = [r for r in results if r.estado == "rechazada"]
    print(f"resumen: {cargadas} cargadas · {len(rechazadas)} rechazadas · {len(results)} archivos revisados")
    return 1 if rechazadas else 0


def cmd_build(args: argparse.Namespace) -> int:
    dbt_args = ["build"]
    if args.select:
        dbt_args += ["--select", args.select]
    return dbt_runner.run_dbt(dbt_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dp", description="Estándar de ingeniería de datos.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingiere las entregas nuevas a landing (idempotente)")
    p_ingest.add_argument("--entrega", help="solo esta entrega (p. ej. carga_2)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_build = sub.add_parser("build", help="dbt build: modelos, tests y contratos")
    p_build.add_argument("--select", help="selector de dbt")
    p_build.set_defaults(func=cmd_build)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
