"""`dp new-source`: esqueleto estándar para una tabla replicada nueva.

Genera la declaración de la fuente (columnas, llave primaria candidata y tests `castea_a` según
el tipo inferido) y el modelo de staging con las macros comunes. No contiene lógica de ningún
dominio: todo sale del encabezado y los valores del CSV. Lo que no puede deducir lo deja
marcado como PENDIENTE para que la persona o el agente lo confirme.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

CONTROL = ("_ab_cdc_lsn", "_ab_cdc_updated_at", "_ab_cdc_deleted_at", "_airbyte_extracted_at")


def snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()


def _is_int(v: str) -> bool:
    return re.fullmatch(r"-?\d+", v) is not None


def _is_num(v: str) -> bool:
    return re.fullmatch(r"-?\d+(\.\d+)?", v) is not None


def _is_ts(v: str) -> bool:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            datetime.strptime(v, fmt)
            return True
        except ValueError:
            continue
    return False


def infer_types(csv_path: Path, sample: int = 5000) -> dict:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        values = {c: [] for c in cols}
        for i, row in enumerate(reader):
            if i >= sample:
                break
            for c in cols:
                v = (row.get(c) or "").strip()
                if v:
                    values[c].append(v)
    types = {}
    for c in cols:
        vals = values[c]
        if not vals:
            types[c] = "texto"
        elif all(_is_int(v) for v in vals):
            types[c] = "entero"
        elif all(_is_num(v) for v in vals):
            types[c] = "numero"
        elif all(_is_ts(v) for v in vals):
            types[c] = "fecha"
        else:
            types[c] = "texto"
    return types


CAST = {"entero": "integer", "numero": "decimal(18,4)", "fecha": "timestamp"}


def source_table_yaml(table: str, types: dict, pk: list) -> str:
    lines = [
        f"      - name: {table}",
        "        description: PENDIENTE describir la tabla (qué es una fila).",
        "        config:",
        "          meta:",
        f"            primary_key: [{', '.join(pk)}]   # PENDIENTE confirmar con `dp profile {table}`",
        "        columns:",
    ]
    for col, t in types.items():
        desc = "Columna de control de la réplica CDC." if col in CONTROL else "PENDIENTE describir."
        lines += [f"          - name: {col}", f"            description: {desc}"]
        if col in CONTROL and col != "_ab_cdc_lsn":
            continue
        cast = "decimal(38,0)" if col == "_ab_cdc_lsn" else CAST.get(t)
        if cast:
            lines += [
                "            data_tests:",
                "              - castea_a:",
                "                  arguments:",
                f"                    tipo: \"{cast}\"",
                "                  config:",
                "                    tags: [engineering]",
            ]
    return "\n".join(lines) + "\n"


def source_file_yaml(system: str, schema: str, table_block: str) -> str:
    return (
        "version: 2\n\nsources:\n"
        f"  - name: {schema}\n"
        f"    description: Réplica Airbyte CDC del sistema {system}. Cada fila es una versión. PENDIENTE describir el sistema.\n"
        f"    schema: {schema}\n"
        "    config:\n"
        "      meta:\n"
        f"        sistema_origen: {system}\n"
        "        replica: airbyte_cdc\n"
        "        dueno_origen: por_confirmar\n"
        '      loaded_at_field: "cast(_airbyte_extracted_at as timestamp)"\n'
        "      freshness:\n"
        "        warn_after: {count: 24, period: hour}\n"
        "        error_after: {count: 48, period: hour}\n"
        "    tables:\n" + table_block
    )


MACRO = {"entero": "entero('{c}')", "numero": "numero('{c}', 18, 4)", "fecha": "fecha_origen('{c}')", "texto": "texto('{c}')"}


def staging_sql(schema: str, table: str, types: dict) -> str:
    business = [c for c in types if c not in CONTROL]
    width = max(len(MACRO[types[c]].format(c=c)) for c in business) + 6
    select = ",\n".join(f"    {{{{ {MACRO[types[c]].format(c=c)} }}}}".ljust(width + 4) + f" as {snake(c)}" for c in business)
    return (
        f"-- {table}: estado actual (última versión CDC, sin borrados). Limpieza 1:1, sin reglas de negocio.\n"
        f"-- Generado por `dp new-source`: revisa tipos y usa codigo() en códigos de catálogo.\n"
        f"with ultima as (\n    {{{{ cdc_ultima_version('{schema}', '{table}') }}}}\n)\n\n"
        f"select\n{select},\n    {{{{ cdc_columnas_control() }}}}\nfrom ultima\n"
    )


def staging_yaml(model: str, schema: str, table: str, pk: list) -> str:
    pk_snake = [snake(c) for c in pk]
    if len(pk_snake) == 1:
        key_tests = (
            f"      - name: {pk_snake[0]}\n        data_tests:\n          - not_null\n"
            "          - unique:\n              config:\n                tags: [engineering]\n"
            "                meta:\n                  verifica: deduplicacion_cdc\n"
        )
        model_tests = ""
    else:
        key_tests = ""
        model_tests = (
            "      - combinacion_unica:\n          arguments:\n"
            f"            columnas: [{', '.join(pk_snake)}]\n"
            "          config:\n            tags: [engineering]\n            meta:\n              verifica: deduplicacion_cdc\n"
        )
    return (
        f"  - name: {model}\n"
        f"    description: PENDIENTE describir. Estado actual de {schema}.{table} (sin borrados).\n"
        "    data_tests:\n"
        f"{model_tests}"
        "      - excluye_borrados:\n          arguments:\n"
        f"            source_name: {schema}\n            table_name: {table}\n"
        f"            llave_modelo: [{', '.join(pk_snake)}]\n"
        "          config:\n            tags: [engineering]\n"
        + (f"    columns:\n{key_tests}" if key_tests else "")
    )


def new_source(dbt_dir: Path, data_dir: Path, table: str, delivery: str, system: str | None, pk: list | None) -> list:
    csv_path = data_dir / delivery / f"{table}.csv"
    if not csv_path.exists():
        raise ValueError(f"no existe {csv_path}")
    system = system or table.split("_", 1)[0]
    schema = f"landing_{system}"
    entity = table.split("_", 1)[1] if "_" in table else table
    model = f"stg_{system}__{entity}"
    types = infer_types(csv_path)
    business = [c for c in types if c not in CONTROL]
    pk = pk or business[:1]
    missing = [c for c in pk if c not in types]
    if missing:
        raise ValueError(f"la llave {missing} no está en el encabezado del CSV")

    folder = dbt_dir / "models" / "staging" / system
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    src_file = folder / f"_{system}__sources.yml"
    block = source_table_yaml(table, types, pk)
    if src_file.exists():
        text = src_file.read_text(encoding="utf-8")
        if re.search(rf"^\s+- name: {re.escape(table)}\s*$", text, re.MULTILINE):
            raise ValueError(f"{table} ya está declarada en {src_file}")
        src_file.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    else:
        src_file.write_text(source_file_yaml(system, schema, block), encoding="utf-8")
    written.append(src_file)

    sql_file = folder / f"{model}.sql"
    if sql_file.exists():
        raise ValueError(f"{sql_file} ya existe")
    sql_file.write_text(staging_sql(schema, table, types), encoding="utf-8")
    written.append(sql_file)

    models_file = folder / f"_{system}__models.yml"
    entry = staging_yaml(model, schema, table, pk)
    if models_file.exists():
        models_file.write_text(models_file.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    else:
        models_file.write_text("version: 2\n\nmodels:\n" + entry, encoding="utf-8")
    written.append(models_file)
    return written
