from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from dp.ingest import ingest_all
from dp.sources import SourceTable

CTRL = ("_ab_cdc_lsn", "_ab_cdc_updated_at", "_ab_cdc_deleted_at", "_airbyte_extracted_at")
DECLARED = {
    "t_viaje": SourceTable(
        schema="landing_t", name="t_viaje", columns=("Id", "Costo") + CTRL, primary_key=("Id",)
    )
}
HEADER = "Id,Costo,_ab_cdc_lsn,_ab_cdc_updated_at,_ab_cdc_deleted_at,_airbyte_extracted_at\n"


def write(path: Path, body: str, header: str = HEADER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")


@pytest.fixture()
def env(tmp_path: Path):
    data = tmp_path / "replica"
    db = tmp_path / "test.duckdb"
    write(
        data / "carga_1" / "t_viaje.csv",
        "1,100,10,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n"
        "2,200,11,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n"
        "2,210,12,2026-01-01T01:00:00Z,,2026-01-02T00:00:00Z\n",
    )
    return data, db


def landing_rows(db: Path) -> int:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("select count(*) from landing_t.t_viaje").fetchone()[0]
    finally:
        con.close()


def registry(db: Path) -> list:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("select id_entrega, estado from ops.entregas order by 1").fetchall()
    finally:
        con.close()


def test_ingesta_es_idempotente(env):
    data, db = env
    first = ingest_all(db, data, DECLARED)
    second = ingest_all(db, data, DECLARED)
    assert [r.estado for r in first] == ["cargada"]
    assert [r.estado for r in second] == ["ya_ingerida"]
    assert landing_rows(db) == 3
    assert registry(db) == [("carga_1", "cargada")]


def test_cuenta_llaves_nuevas_existentes_y_borrados(env):
    data, db = env
    ingest_all(db, data, DECLARED)
    write(
        data / "carga_2" / "t_viaje.csv",
        "2,220,13,2026-01-03T00:00:00Z,,2026-01-04T00:00:00Z\n"
        "3,300,14,2026-01-03T00:00:00Z,,2026-01-04T00:00:00Z\n"
        "1,100,15,2026-01-03T00:00:00Z,2026-01-03T00:00:00Z,2026-01-04T00:00:00Z\n",
    )
    (r,) = ingest_all(db, data, DECLARED, only="carga_2")
    assert (r.estado, r.filas, r.llaves_nuevas, r.llaves_existentes, r.filas_borrado) == ("cargada", 3, 1, 2, 1)


def test_reenvio_con_mismo_contenido_se_registra_como_duplicada(env):
    data, db = env
    ingest_all(db, data, DECLARED)
    shutil.copytree(data / "carga_1", data / "carga_2")
    results = ingest_all(db, data, DECLARED)
    assert [r.estado for r in results] == ["ya_ingerida", "duplicada"]
    assert landing_rows(db) == 3


def test_archivo_modificado_despues_de_ingerir_se_rechaza(env):
    data, db = env
    ingest_all(db, data, DECLARED)
    write(data / "carga_1" / "t_viaje.csv", "9,999,99,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n")
    (r,) = ingest_all(db, data, DECLARED)
    assert r.estado == "rechazada" and "inmutables" in r.motivo
    assert landing_rows(db) == 3
    assert registry(db) == [("carga_1", "cargada")]


def test_tabla_no_declarada_se_rechaza(env):
    data, db = env
    write(data / "carga_1" / "t_desconocida.csv", "1,1,1,x,,y\n")
    estados = {r.archivo: r.estado for r in ingest_all(db, data, DECLARED)}
    assert estados == {"t_desconocida.csv": "rechazada", "t_viaje.csv": "cargada"}


def test_deriva_de_esquema_se_registra_y_landing_conserva_todo(env):
    data, db = env
    ingest_all(db, data, DECLARED)
    write(
        data / "carga_2" / "t_viaje.csv",
        "4,16,2026-01-05T00:00:00Z,,2026-01-06T00:00:00Z,nuevo\n",
        header="Id,_ab_cdc_lsn,_ab_cdc_updated_at,_ab_cdc_deleted_at,_airbyte_extracted_at,Extra\n",
    )
    (r,) = ingest_all(db, data, DECLARED, only="carga_2")
    assert r.estado == "cargada"
    assert r.columnas_faltantes == ["Costo"]
    assert r.columnas_nuevas == ["Extra"]
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("select Costo, Extra from landing_t.t_viaje where Id = '4'").fetchone() == (None, "nuevo")
    finally:
        con.close()


def test_falta_la_llave_primaria_se_rechaza(env):
    data, db = env
    write(
        data / "carga_2" / "t_viaje.csv",
        "100,16,2026-01-05T00:00:00Z,,2026-01-06T00:00:00Z\n",
        header="Costo,_ab_cdc_lsn,_ab_cdc_updated_at,_ab_cdc_deleted_at,_airbyte_extracted_at\n",
    )
    (r,) = ingest_all(db, data, DECLARED, only="carga_2")
    assert r.estado == "rechazada" and "llave" in r.motivo
