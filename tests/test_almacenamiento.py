from datetime import date

from radar.almacenamiento import BaseDatos, exportar


def _fila(codigo, cierre, nombre="x"):
    return {"codigo": codigo, "nombre": nombre, "fecha_cierre": cierre, "rubro": "aseo"}


def test_upsert_y_vigentes(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    db.guardar_licitaciones([_fila("A", "2026-10-20 15:00:00"), _fila("B", "2026-10-01 15:00:00")])
    primera = db.con.execute("SELECT primera_deteccion FROM licitaciones WHERE codigo='A'").fetchone()[0]
    db.guardar_licitaciones([_fila("A", "2026-10-20 15:00:00", nombre="nuevo")])

    df = db.licitaciones_vigentes(hoy=date(2026, 10, 10))
    assert list(df["codigo"]) == ["A"]
    assert df.loc[0, "nombre"] == "nuevo"
    assert df.loc[0, "primera_deteccion"] == primera
    assert df.loc[0, "dias_restantes"] == 10


def test_exportar_crea_archivos(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    db.guardar_licitaciones([_fila("A", "2026-10-20 15:00:00")])
    rutas = exportar(db.licitaciones_vigentes(date(2026, 10, 10)), tmp_path / "exp", "licitaciones", date(2026, 10, 10))
    assert {r.name for r in rutas} == {
        "licitaciones_2026-10-10.csv", "licitaciones_2026-10-10.xlsx",
        "licitaciones_actual.csv", "licitaciones_actual.xlsx",
    }
