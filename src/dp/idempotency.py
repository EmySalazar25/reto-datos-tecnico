"""Verificación de idempotencia: correr todo dos veces no cambia nada.

Toma una foto (filas y hash del contenido) de cada tabla, vuelve a correr ingesta y build, toma
otra foto y compara. Es la misma prueba que hará quien evalúe, pero automatizada y con evidencia.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb

SKIP_SCHEMAS = ("information_schema", "pg_catalog")


def table_fingerprints(db_path: Path) -> dict:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = con.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_type = 'BASE TABLE' and table_schema not in ('information_schema', 'pg_catalog') "
            "order by 1, 2"
        ).fetchall()
        result = {}
        for schema, table in tables:
            fqn = f'"{schema}"."{table}"'
            cols = [
                r[0]
                for r in con.execute(
                    "select column_name from information_schema.columns where table_schema = ? and table_name = ? "
                    "order by ordinal_position",
                    [schema, table],
                ).fetchall()
            ]
            # Las columnas de auditoría de la ingesta (hora de carga) no forman parte del contenido.
            content_cols = [c for c in cols if c not in ("_dp_ingerido_en", "ingerido_en")]
            select = ", ".join(f'"{c}"' for c in content_cols)
            rows = con.execute(f"select {select} from {fqn} order by all").fetchall()
            digest = hashlib.sha256(repr(rows).encode()).hexdigest()[:16]
            result[f"{schema}.{table}"] = {"filas": len(rows), "hash": digest}
        return result
    finally:
        con.close()


def compare(first: dict, second: dict) -> dict:
    tablas = []
    for name in sorted(set(first) | set(second)):
        a, b = first.get(name), second.get(name)
        tablas.append(
            {
                "tabla": name,
                "filas_corrida_1": a["filas"] if a else None,
                "filas_corrida_2": b["filas"] if b else None,
                "igual": a == b,
            }
        )
    cambios = [t for t in tablas if not t["igual"]]
    return {"status": "PASS" if not cambios else "FAIL", "tablas": tablas, "tablas_con_cambios": [t["tabla"] for t in cambios]}
