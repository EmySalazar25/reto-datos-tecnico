"""Perfilado de una tabla: lo que hay que saber antes de modelarla.

Para una tabla de landing (réplica CDC) mide lo que rompe los marts en silencio: versiones por
llave, duplicados exactos, borrados, empates de timestamp que solo el LSN resuelve, valores con
espacios o variantes de mayúsculas, fechas centinela y valores que no convierten a su tipo.
La salida es corta a propósito: un LLM con plan gratuito no debe leer la tabla, sino esto.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

CONTROL = ("_ab_cdc_lsn", "_ab_cdc_updated_at", "_ab_cdc_deleted_at", "_airbyte_extracted_at")
LINEAGE_PREFIX = "_dp_"


def _q(c: str) -> str:
    return '"' + c.replace('"', '""') + '"'


def resolve(con, name: str, declared: dict) -> tuple:
    if "." in name:
        schema, table = name.split(".", 1)
        return schema, table
    if name in declared:
        return declared[name].schema, name
    rows = con.execute(
        "select table_schema from information_schema.tables where table_name = ? order by 1", [name]
    ).fetchall()
    if len(rows) != 1:
        raise ValueError(f"tabla '{name}' no encontrada o ambigua: {[r[0] for r in rows]}")
    return rows[0][0], name


def profile(db_path: Path, name: str, declared: dict) -> dict:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        schema, table = resolve(con, name, declared)
        fqn = f"{_q(schema)}.{_q(table)}"
        cols = [r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_schema = ? and table_name = ? "
            "order by ordinal_position", [schema, table]).fetchall()]
        if not cols:
            raise ValueError(f"{schema}.{table} no existe")
        out = {"tabla": f"{schema}.{table}", "filas": con.execute(f"select count(*) from {fqn}").fetchone()[0]}
        business = [c for c in cols if c not in CONTROL and not c.startswith(LINEAGE_PREFIX) and not c.startswith("_cdc")]
        is_cdc = "_ab_cdc_lsn" in cols
        src = declared.get(table)
        if is_cdc and src:
            out["cdc"] = _cdc_stats(con, fqn, list(src.primary_key), business)
        out["columnas"] = [_column_stats(con, fqn, c, is_text=is_cdc) for c in business]
        return out
    finally:
        con.close()


def _cdc_stats(con, fqn: str, pk: list, business: list) -> dict:
    pkc = ", ".join(_q(c) for c in pk)
    content = ", ".join(_q(c) for c in business + list(CONTROL))
    lsn = "try_cast(_ab_cdc_lsn as decimal(38,0))"
    q = lambda sql: con.execute(sql).fetchone()
    llaves, max_v = q(f"select count(*), max(n) from (select count(*) n from {fqn} group by {pkc})")
    dup = q(f"select coalesce(sum(n - 1), 0) from (select count(*) n from {fqn} group by {content} having count(*) > 1)")[0]
    borr_filas = q(f"select count(*) from {fqn} where _ab_cdc_deleted_at is not null")[0]
    borr_llaves = q(
        f"select count(*) from (select *, row_number() over (partition by {pkc} order by {lsn} desc) rn from {fqn}) "
        f"where rn = 1 and _ab_cdc_deleted_at is not null")[0]
    empates = q(
        f"select count(*) from (select {pkc}, _ab_cdc_updated_at from {fqn} group by {pkc}, _ab_cdc_updated_at "
        f"having count(distinct _ab_cdc_lsn) > 1)")[0]
    entregas = [r[0] for r in con.execute(f"select distinct _dp_entrega from {fqn} order by 1").fetchall()] \
        if "_dp_entrega" in [d[0] for d in con.execute(f"describe {fqn}").fetchall()] else []
    return {
        "llave": pk, "llaves_distintas": llaves, "max_versiones_por_llave": max_v,
        "filas_duplicadas_exactas": int(dup), "filas_de_borrado": borr_filas,
        "llaves_cuya_ultima_version_es_borrado": borr_llaves,
        "llaves_con_empate_de_timestamp_y_lsn_distinto": empates, "entregas": entregas,
    }


def _column_stats(con, fqn: str, c: str, is_text: bool) -> dict:
    col = _q(c)
    q = lambda sql: con.execute(sql).fetchone()
    stats = {"columna": c}
    nulos, distintos = q(f"select count(*) filter (where {col} is null), count(distinct {col}) from {fqn}")
    stats.update({"nulos": nulos, "distintos": distintos})
    if is_text:
        txt = f"cast({col} as varchar)"
        no_vacios = q(f"select count(*) from {fqn} where nullif(trim({txt}), '') is not null")[0] or 1
        espacios, normalizados, centinela, num_ok, ts_ok = q(
            f"select count(*) filter (where {txt} <> trim({txt})), count(distinct upper(trim({txt}))), "
            f"count(*) filter (where trim({txt}) like '1900-01-01%'), "
            f"count(*) filter (where try_cast(trim({txt}) as double) is not null), "
            f"count(*) filter (where try_cast(trim({txt}) as timestamp) is not null) from {fqn}")
        if espacios:
            stats["con_espacios"] = espacios
        if normalizados < distintos:
            stats["variantes_por_mayusculas_o_espacios"] = distintos - normalizados
        if centinela:
            stats["fecha_centinela_1900"] = centinela
        for tipo, ok in (("numero", num_ok), ("fecha", ts_ok)):
            if 0.9 <= ok / no_vacios < 1:
                stats[f"no_convierten_a_{tipo}"] = no_vacios - ok
            if ok == no_vacios:
                stats["tipo_probable"] = tipo
                break
    if distintos and distintos <= 25:
        stats["valores"] = {str(v): n for v, n in con.execute(
            f"select {col}, count(*) from {fqn} group by 1 order by 2 desc limit 25").fetchall()}
    return stats


def render(p: dict) -> str:
    lines = [f"tabla: {p['tabla']} · {p['filas']} filas"]
    if "cdc" in p:
        c = p["cdc"]
        lines.append(
            f"cdc: llave {c['llave']} · {c['llaves_distintas']} llaves · hasta {c['max_versiones_por_llave']} versiones por llave"
        )
        lines.append(
            f"     {c['filas_duplicadas_exactas']} filas duplicadas exactas · {c['filas_de_borrado']} filas de borrado "
            f"({c['llaves_cuya_ultima_version_es_borrado']} llaves borradas hoy) · "
            f"{c['llaves_con_empate_de_timestamp_y_lsn_distinto']} llaves con empate de timestamp (solo el LSN ordena)"
        )
    for col in p["columnas"]:
        extras = {k: v for k, v in col.items() if k not in ("columna", "nulos", "distintos", "valores")}
        line = f"- {col['columna']}: {col['nulos']} nulos · {col['distintos']} distintos"
        if extras:
            line += " · " + " · ".join(f"{k}={v}" for k, v in extras.items())
        lines.append(line)
        if "valores" in col:
            lines.append("    valores: " + ", ".join(f"{k!r}:{v}" for k, v in col["valores"].items()))
    return "\n".join(lines)
