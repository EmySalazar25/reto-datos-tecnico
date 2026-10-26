"""Punto de entrada `dp`. Cada subcomando devuelve una salida corta, útil para personas y para el agente."""

from __future__ import annotations

import argparse
import sys

from dp import dbt_runner


def cmd_build(args: argparse.Namespace) -> int:
    dbt_args = ["build"]
    if args.select:
        dbt_args += ["--select", args.select]
    return dbt_runner.run_dbt(dbt_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dp", description="Estándar de ingeniería de datos.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="dbt build: modelos, tests y contratos")
    p_build.add_argument("--select", help="selector de dbt")
    p_build.set_defaults(func=cmd_build)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
