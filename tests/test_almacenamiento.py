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


def test_depurar_vigentes_elimina_las_que_ya_no_calzan(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    db.guardar_licitaciones([
        _fila("A", "2026-10-20 15:00:00"),
        _fila("B", "2026-10-20 15:00:00"),
        _fila("C", "2026-10-01 15:00:00"),  # cerrada: se conserva como historial
    ])
    assert db.depurar_vigentes({"A"}, hoy=date(2026, 10, 10)) == 1
    codigos = {c for (c,) in db.con.execute("SELECT codigo FROM licitaciones")}
    assert codigos == {"A", "C"}


def test_migra_base_antigua_sin_columnas_nuevas(tmp_path):
    import sqlite3
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE licitaciones (codigo TEXT PRIMARY KEY, nombre TEXT, fecha_cierre TEXT, "
                "rubro TEXT, primera_deteccion TEXT, ultima_actualizacion TEXT)")
    con.execute("CREATE TABLE ordenes_compra_items (codigo_oc TEXT, correlativo INTEGER, producto TEXT, "
                "PRIMARY KEY (codigo_oc, correlativo))")
    con.commit()
    con.close()
    db = BaseDatos(ruta)
    db.guardar_licitaciones([_fila("A", "2026-10-20 15:00:00") | {"alertas_regulatorias": "x", "solo_regulados": 1}])
    db.reemplazar_items_oc("OC", [{"codigo_oc": "OC", "correlativo": 1, "producto": "Cloro",
                                   "alertas_regulatorias": "y"}])
    assert db.licitaciones_vigentes(date(2026, 10, 10)).loc[0, "alertas_regulatorias"] == "x"
    assert db.items_oc().loc[0, "alertas_regulatorias"] == "y"


def test_exportar_neutraliza_formulas_y_usa_coma_decimal(tmp_path):
    import pandas as pd
    from radar.almacenamiento import exportar
    df = pd.DataFrame({"nombre": ["= a lo solicitado", "Resmas"], "monto": [1.5, 2.0]})
    csv = [r for r in exportar(df, tmp_path, "prueba") if r.suffix == ".csv"][0]
    texto = csv.read_text(encoding="utf-8-sig")
    assert "'= a lo solicitado" in texto and "1,5" in texto
    leido = pd.read_csv(csv, sep=";", decimal=",", encoding="utf-8-sig")
    assert leido["monto"].tolist() == [1.5, 2.0]


def test_exportar_quita_caracteres_de_control_que_excel_rechaza(tmp_path):
    # Caso real (OC de la API, 24-10-2026): «sigla 10U\x02POCA-202» hacía fallar la exportación.
    import pandas as pd
    from openpyxl import load_workbook

    from radar.almacenamiento import sin_formulas
    df = pd.DataFrame({"descripcion": ["Calzas CAT 336DL, sigla 10U\x02POCA-202", "", "-5 %"], "n": [1, 2, 3]})
    xlsx = [r for r in exportar(df, tmp_path, "oc_items") if r.suffix == ".xlsx"][0]
    valores = [c.value for c in load_workbook(xlsx).active["A"][1:]]
    assert valores[0] == "Calzas CAT 336DL, sigla 10UPOCA-202" and valores[2] == "'-5 %"
    assert sin_formulas(df)["descripcion"].tolist()[1] == ""        # vacío no se vuelve «'»
