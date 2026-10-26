"""Ingesta idempotente de entregas de la réplica a la capa landing (bronze).

Reglas:
- Una entrega es una carpeta `data/replica/<id>/` con un CSV por tabla fuente.
- Las entregas son inmutables: un archivo ya ingerido no se vuelve a cargar, y si cambió
  su contenido se rechaza.
- Un archivo con el mismo contenido que otro ya ingerido (reenvío) se registra como
  `duplicada` y no se carga.
- Solo se aceptan tablas declaradas en el YAML de dbt.
- landing conserva cada versión CDC tal cual llega (texto), más columnas de linaje `_dp_*`.
- Cada archivo se carga en una transacción junto con su registro: o queda todo o nada.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from dp.sources import SourceTable

REGISTRY = "ops.entregas"
LINEAGE_COLUMNS = ("_dp_entrega", "_dp_archivo", "_dp_sha256", "_dp_ingerido_en")


@dataclass
class FileResult:
    entrega: str
    archivo: str
    tabla: str
    estado: str  # cargada | duplicada | rechazada | ya_ingerida
    motivo: str = ""
    filas: int = 0
    llaves_nuevas: int = 0
    llaves_existentes: int = 0
    filas_borrado: int = 0
    columnas_faltantes: list = field(default_factory=list)
    columnas_nuevas: list = field(default_factory=list)

    def line(self) -> str:
        base = f"{self.entrega:<10} {self.archivo:<20} {self.estado:<11}"
        if self.estado == "cargada":
            esquema = "esquema ok"
            if self.columnas_faltantes:
                esquema = f"FALTAN columnas {self.columnas_faltantes}"
            elif self.columnas_nuevas:
                esquema = f"columnas nuevas {self.columnas_nuevas}"
            return (
                f"{base} {self.filas} filas · {self.llaves_nuevas} llaves nuevas · "
                f"{self.llaves_existentes} existentes · {self.filas_borrado} borrados · {esquema}"
            )
        return f"{base} {self.motivo}"


def _natural_key(path: Path):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", path.name)]


def list_deliveries(data_dir: Path) -> list:
    if not data_dir.exists():
        return []
    return sorted((p for p in data_dir.iterdir() if p.is_dir()), key=_natural_key)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def ensure_registry(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists ops")
    con.execute(
        f"""
        create table if not exists {REGISTRY} (
            id_entrega          varchar not null,
            archivo             varchar not null,
            tabla_destino       varchar,
            sha256              varchar not null,
            estado              varchar not null,
            motivo              varchar,
            filas               bigint,
            llaves_nuevas       bigint,
            llaves_existentes   bigint,
            filas_borrado       bigint,
            columnas_observadas varchar,
            columnas_faltantes  varchar,
            columnas_nuevas     varchar,
            max_extraido_en     varchar,
            ingerido_en         timestamp not null,
            primary key (id_entrega, archivo)
        )
        """
    )


def _existing_columns(con, schema: str, table: str) -> list:
    rows = con.execute(
        "select column_name from information_schema.columns "
        "where table_schema = ? and table_name = ? order by ordinal_position",
        [schema, table],
    ).fetchall()
    return [r[0] for r in rows]


def _ensure_landing_table(con, src: SourceTable, observed: list) -> None:
    con.execute(f"create schema if not exists {_q(src.schema)}")
    existing = _existing_columns(con, src.schema, src.name)
    if not existing:
        cols = list(src.columns) + [c for c in observed if c not in src.columns]
        ddl = ", ".join(f"{_q(c)} varchar" for c in cols)
        lineage = ", ".join(
            f"{_q(c)} {'timestamp' if c == '_dp_ingerido_en' else 'varchar'}" for c in LINEAGE_COLUMNS
        )
        con.execute(f"create table {_q(src.schema)}.{_q(src.name)} ({ddl}, {lineage})")
        return
    for c in observed:
        if c not in existing:
            # landing conserva todo lo que llega: una columna nueva se agrega, no se descarta.
            con.execute(f"alter table {_q(src.schema)}.{_q(src.name)} add column {_q(c)} varchar")


def _reject(con, entrega, archivo, tabla, sha, motivo, now) -> FileResult:
    con.execute(f"delete from {REGISTRY} where id_entrega = ? and archivo = ?", [entrega, archivo])
    con.execute(
        f"insert into {REGISTRY} (id_entrega, archivo, tabla_destino, sha256, estado, motivo, ingerido_en) "
        "values (?, ?, ?, ?, 'rechazada', ?, ?)",
        [entrega, archivo, tabla, sha, motivo, now],
    )
    return FileResult(entrega, archivo, tabla or "-", "rechazada", motivo)


def ingest_file(con, entrega: str, csv_path: Path, declared: dict, now: datetime) -> FileResult:
    archivo = csv_path.name
    sha = sha256_of(csv_path)
    src = declared.get(csv_path.stem)

    prior = con.execute(
        f"select sha256, estado from {REGISTRY} where id_entrega = ? and archivo = ?", [entrega, archivo]
    ).fetchone()
    if prior and prior[1] != "rechazada":
        if prior[0] == sha:
            return FileResult(entrega, archivo, src.fqn if src else "-", "ya_ingerida", "sin cambios")
        # No se toca el registro original: la entrega ya cargada es la que vale.
        return FileResult(
            entrega, archivo, src.fqn if src else "-", "rechazada",
            "el archivo cambió después de ingerirse; las entregas son inmutables (usa una carpeta nueva)",
        )

    if src is None:
        return _reject(con, entrega, archivo, None, sha, "tabla no declarada en el YAML de dbt (usa dp new-source)", now)

    dup = con.execute(
        f"select id_entrega from {REGISTRY} where sha256 = ? and tabla_destino = ? and estado = 'cargada'",
        [sha, src.fqn],
    ).fetchone()
    if dup:
        con.execute(f"delete from {REGISTRY} where id_entrega = ? and archivo = ?", [entrega, archivo])
        con.execute(
            f"insert into {REGISTRY} (id_entrega, archivo, tabla_destino, sha256, estado, motivo, ingerido_en) "
            "values (?, ?, ?, ?, 'duplicada', ?, ?)",
            [entrega, archivo, src.fqn, sha, f"mismo contenido que {dup[0]}", now],
        )
        return FileResult(entrega, archivo, src.fqn, "duplicada", f"mismo contenido que {dup[0]}; no se carga")

    con.execute(
        "create or replace temp table _dp_archivo as "
        "select * from read_csv(?, all_varchar = true, header = true)",
        [str(csv_path)],
    )
    observed = [r[0] for r in con.execute("select column_name from (describe _dp_archivo)").fetchall()]
    missing_pk = [c for c in src.primary_key if c not in observed]
    if missing_pk:
        return _reject(con, entrega, archivo, src.fqn, sha, f"faltan columnas de la llave {missing_pk}", now)

    faltantes = [c for c in src.columns if c not in observed]
    nuevas = [c for c in observed if c not in src.columns]

    con.execute("begin transaction")
    try:
        _ensure_landing_table(con, src, observed)
        target = f"{_q(src.schema)}.{_q(src.name)}"
        pk_file = ", ".join(_q(c) for c in src.primary_key)
        pk_join = " and ".join(f"l.{_q(c)} = f.{_q(c)}" for c in src.primary_key)

        filas, borrados, max_ext = con.execute(
            "select count(*), count(*) filter (where \"_ab_cdc_deleted_at\" is not null), "
            "max(\"_airbyte_extracted_at\") from _dp_archivo"
            if "_ab_cdc_deleted_at" in observed and "_airbyte_extracted_at" in observed
            else "select count(*), 0, null from _dp_archivo"
        ).fetchone()
        existentes = con.execute(
            f"select count(*) from (select distinct {pk_file} from _dp_archivo) f "
            f"where exists (select 1 from {target} l where {pk_join})"
        ).fetchone()[0]
        distintas = con.execute(f"select count(*) from (select distinct {pk_file} from _dp_archivo)").fetchone()[0]

        cols = ", ".join(_q(c) for c in observed)
        con.execute(
            f"insert into {target} ({cols}, {', '.join(LINEAGE_COLUMNS)}) "
            f"select {cols}, ?, ?, ?, ? from _dp_archivo",
            [entrega, archivo, sha, now],
        )
        # Si antes se rechazó (p. ej. la fuente aún no estaba declarada), el reintento reemplaza ese registro.
        con.execute(f"delete from {REGISTRY} where id_entrega = ? and archivo = ?", [entrega, archivo])
        con.execute(
            f"insert into {REGISTRY} values (?, ?, ?, ?, 'cargada', null, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                entrega, archivo, src.fqn, sha, filas, distintas - existentes, existentes, borrados,
                json.dumps(observed), json.dumps(faltantes), json.dumps(nuevas), max_ext, now,
            ],
        )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.execute("drop table if exists _dp_archivo")

    return FileResult(
        entrega, archivo, src.fqn, "cargada", "", filas, distintas - existentes, existentes, borrados, faltantes, nuevas
    )


def ingest_all(db_path: Path, data_dir: Path, declared: dict, only=None) -> list:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    results = []
    con = duckdb.connect(str(db_path))
    try:
        ensure_registry(con)
        for delivery in list_deliveries(data_dir):
            if only and delivery.name != only:
                continue
            for csv_path in sorted(delivery.glob("*.csv")):
                results.append(ingest_file(con, delivery.name, csv_path, declared, now))
    finally:
        con.close()
    return results
