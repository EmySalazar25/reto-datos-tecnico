from __future__ import annotations

import pytest

from dp import chaos

SQL = """with viajes as (
    select
        anio_mes,
        sum(costo) as costo
    from x
    group by anio_mes
)
select * from viajes
"""


def test_parche_conserva_la_indentacion_del_archivo():
    out = chaos.apply_patch(SQL, "select\nanio_mes,\nsum(costo) as costo", "select\n    anio_mes,\n    sum(costo * 2) as costo")
    assert "        sum(costo * 2) as costo" in out
    assert out.count("anio_mes") == 2  # select y group by; nada duplicado


def test_parche_es_reversible():
    patched = chaos.apply_patch(SQL, "group by anio_mes", "group by anio_mes, 2")
    assert chaos.apply_patch(patched, "group by anio_mes, 2", "group by anio_mes") == SQL


def test_fragmento_ambiguo_o_inexistente_es_error():
    with pytest.raises(chaos.ChaosError):
        chaos.apply_patch(SQL, "no existe", "x")
    with pytest.raises(chaos.ChaosError):
        chaos.apply_patch(SQL + "group by anio_mes\n", "group by anio_mes", "x")


def test_chaos_bloqueado_fuera_de_dev_y_ci(monkeypatch):
    monkeypatch.setenv("DP_ENTORNO", "prod")
    with pytest.raises(chaos.ChaosError):
        chaos.guard()
    monkeypatch.setenv("DP_ENTORNO", "ci")
    assert chaos.guard() == "ci"


def test_catalogo_declara_lo_necesario_y_cada_inyeccion_aplica():
    from dp import paths

    for s in chaos.load_catalog():
        assert {"id", "nombre", "tipo", "rompe", "mecanismo", "debe_detectar", "estado_esperado"} <= set(s), s["id"]
        if s["tipo"] == "codigo":
            target = paths.DBT_DIR / s["inyeccion"]["archivo"]
            chaos.apply_patch(target.read_text(encoding="utf-8"), s["inyeccion"]["buscar"], s["inyeccion"]["reemplazar"])
