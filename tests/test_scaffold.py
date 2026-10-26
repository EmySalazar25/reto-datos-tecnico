"""`dp new-source` con una fuente de otro dominio: el esqueleto generado se ingiere, compila y
pasa sus tests sin editarlo. Así se prueba que el estándar no depende de Logística."""

from __future__ import annotations

import shutil

import duckdb

from dp import dbt_runner, paths
from dp.ingest import ingest_all
from dp.scaffold import new_source, snake
from dp.sources import load_declared_sources

CSV = (
    "ClaEquipo,NomEquipo,HorasOperables,FechaAlta,_ab_cdc_lsn,_ab_cdc_updated_at,_ab_cdc_deleted_at,_airbyte_extracted_at\n"
    "1,Grua 1,700.5,2026-01-01 00:00:00,10,2026-01-01T00:00:00.000Z,,2026-02-01T08:00:00.000Z\n"
    "1,Grua 1 ,710.0,2026-01-01 00:00:00,11,2026-01-01T00:00:00.000Z,,2026-02-01T08:00:00.000Z\n"
    "2,Horno,600,1900-01-01 00:00:00,20,2026-01-02T00:00:00.000Z,,2026-02-01T08:00:00.000Z\n"
    "3,Banda,500,2026-01-03 00:00:00,30,2026-01-03T00:00:00.000Z,,2026-02-01T08:00:00.000Z\n"
    "3,Banda,500,2026-01-03 00:00:00,31,2026-01-04T00:00:00.000Z,2026-01-04T00:00:00.000Z,2026-02-01T08:00:00.000Z\n"
)


def test_snake_case():
    assert snake("ClaEquipo") == "cla_equipo" and snake("HorasOperables") == "horas_operables"


def test_fuente_nueva_de_otro_dominio_queda_lista_y_pasa_sus_tests(tmp_path):
    dbt_dir = tmp_path / "dbt"
    shutil.copytree(paths.DBT_DIR, dbt_dir, ignore=shutil.ignore_patterns("target", "logs"))
    data = tmp_path / "replica"
    (data / "carga_1").mkdir(parents=True)
    (data / "carga_1" / "mto_equipo.csv").write_text(CSV, encoding="utf-8")

    written = new_source(dbt_dir, data, "mto_equipo", "carga_1", None, None)
    assert {w.name for w in written} == {"_mto__sources.yml", "stg_mto__equipo.sql", "_mto__models.yml"}

    db = tmp_path / "t.duckdb"
    declared = load_declared_sources(dbt_dir)
    assert declared["mto_equipo"].primary_key == ("ClaEquipo",)
    ingest_all(db, data, {"mto_equipo": declared["mto_equipo"]})
    code = dbt_runner.run_dbt(["build", "--select", "+stg_mto__equipo"], project_dir=dbt_dir, db_path=db, quiet=True)
    assert code == 0

    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "select cla_equipo, nom_equipo, horas_operables, fecha_alta from staging.stg_mto__equipo order by 1"
        ).fetchall()
    finally:
        con.close()
    # Última versión por LSN, sin el equipo borrado, texto sin espacios y centinela como nulo.
    assert [(r[0], r[1], float(r[2]), r[3] is None) for r in rows] == [(1, "Grua 1", 710.0, False), (2, "Horno", 600.0, True)]
