from __future__ import annotations

from dp.ingest import ingest_all
from dp.profile import profile
from dp.sources import SourceTable

CTRL = ("_ab_cdc_lsn", "_ab_cdc_updated_at", "_ab_cdc_deleted_at", "_airbyte_extracted_at")
DECLARED = {"t_viaje": SourceTable(schema="landing_t", name="t_viaje", columns=("Id", "Estatus") + CTRL, primary_key=("Id",))}


def test_perfil_cdc_detecta_duplicados_borrados_empates_y_variantes(tmp_path):
    data = tmp_path / "replica" / "carga_1"
    data.mkdir(parents=True)
    (data / "t_viaje.csv").write_text(
        "Id,Estatus,_ab_cdc_lsn,_ab_cdc_updated_at,_ab_cdc_deleted_at,_airbyte_extracted_at\n"
        "1,ENT,10,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n"
        "1,ENT,10,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n"   # duplicado exacto
        "1,ent ,11,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n"  # mismo timestamp, otro LSN
        "2,TRA,20,2026-01-01T00:00:00Z,,2026-01-02T00:00:00Z\n"
        "2,TRA,21,2026-01-03T00:00:00Z,2026-01-03T00:00:00Z,2026-01-02T00:00:00Z\n",  # borrado
        encoding="utf-8",
    )
    db = tmp_path / "t.duckdb"
    ingest_all(db, tmp_path / "replica", DECLARED)
    p = profile(db, "t_viaje", DECLARED)
    cdc = p["cdc"]
    assert (cdc["llaves_distintas"], cdc["filas_duplicadas_exactas"]) == (2, 1)
    assert cdc["llaves_cuya_ultima_version_es_borrado"] == 1
    assert cdc["llaves_con_empate_de_timestamp_y_lsn_distinto"] == 1
    estatus = next(c for c in p["columnas"] if c["columna"] == "Estatus")
    assert estatus["con_espacios"] == 1 and estatus["variantes_por_mayusculas_o_espacios"] == 1
