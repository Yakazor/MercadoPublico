import pandas as pd
import pytest

from radar.modelos import VERSION_DETALLE_LICITACION, compactar_licitacion
from radar.presupuesto import IVA, ReferenciasOC, armar_presupuesto, items_licitacion_presupuesto

PRECIOS = pd.DataFrame([
    {"rubro": "oficina_libreria", "producto_normalizado": "papel para fotocopiadora o impresora", "moneda": "CLP",
     "precio_mediana": 3164.0, "precio_p25": 2800.0, "n_ordenes": 48},
    {"rubro": "insumos_medicos_aseo", "producto_normalizado": "guantes medicos de examen o para usos no quirurgic",
     "moneda": "CLP", "precio_mediana": 390.0, "precio_p25": 240.0, "n_ordenes": 11},
    {"rubro": "computacion_electronica", "producto_normalizado": "toner", "moneda": "USD",
     "precio_mediana": 50.0, "precio_p25": 40.0, "n_ordenes": 3},
])

DETALLE = {
    "CodigoExterno": "123-4-LE26",
    "Items": {"Listado": [
        {"Correlativo": 1, "NombreProducto": "Papel para fotocopiadora o impresora", "Descripcion": "Resma carta 75 g",
         "Cantidad": 200, "UnidadMedida": "Resma", "Categoria": "Papel"},
        {"Correlativo": 2, "NombreProducto": "Guantes de examen", "Descripcion": "guantes medicos nitrilo examen talla M",
         "Cantidad": "10", "UnidadMedida": "Caja"},
        {"Correlativo": 3, "NombreProducto": "Tóner", "Descripcion": "Tóner HP 85A", "Cantidad": 4, "UnidadMedida": "Unidad"},
    ]},
}


def test_compactar_guarda_cantidad_unidad_y_version():
    compacto = compactar_licitacion(DETALLE)
    assert compacto["_version"] == VERSION_DETALLE_LICITACION
    item = compacto["Items"]["Listado"][0]
    assert (item["Correlativo"], item["Cantidad"], item["UnidadMedida"]) == (1, 200, "Resma")


def test_referencia_exacta_parecida_y_solo_clp():
    filas = items_licitacion_presupuesto("123-4-LE26", "oficina_libreria", DETALLE, ReferenciasOC(PRECIOS))
    papel, guantes, toner = filas
    # Mismo producto ONU
    assert papel["ref_mediana"] == 3164.0 and papel["ref_similitud"] == 1.0
    assert (papel["cantidad"], papel["unidad"], papel["linea"]) == (200.0, "Resma", 1)
    # Parecido por palabras (producto + descripción)
    assert guantes["ref_producto"].startswith("guantes medicos de examen")
    assert guantes["cantidad"] == 10.0
    # El tóner solo tiene precio en USD: no sirve de referencia en pesos
    assert toner["ref_mediana"] is None


def test_sin_referencias_no_falla():
    filas = items_licitacion_presupuesto("X", None, {"Items": {"Listado": [{"NombreProducto": "Sillas"}]}})
    assert filas[0]["linea"] == 1 and filas[0]["ref_mediana"] is None and filas[0]["cantidad"] is None


def test_armar_presupuesto_usa_el_precio_mas_bajo_y_suma_iva():
    items = [
        {"linea": 1, "cantidad": 10, "ref_mediana": 3000.0},
        {"linea": 2, "cantidad": 2, "ref_mediana": None},
        {"linea": 3, "cantidad": 1, "ref_mediana": 500.0},
    ]
    mercado = [
        {"linea": 1, "tienda": "A", "precio_unitario_neto": 2000, "url": "https://a.cl/x"},
        {"linea": 1, "tienda": "B", "precio_unitario_neto": 1800, "url": "https://b.cl/x"},
        {"linea": 2, "tienda": "C", "precio_unitario_neto": None},
    ]
    p = armar_presupuesto(items, mercado, margen=0.2, otros_costos=0.0)
    uno = p["items"][0]
    assert uno["tienda"] == "B" and uno["url"] == "https://b.cl/x"
    assert uno["costo_unitario_neto"] == 1800 and uno["oferta_unitaria_neta"] == pytest.approx(2160)
    assert uno["margen_vs_referencia"] == pytest.approx(3000 / 1800 - 1)
    assert p["items_sin_precio"] == 2
    assert p["costo_neto"] == pytest.approx(18000)
    assert p["oferta_neta"] == pytest.approx(21600)
    assert p["oferta_total"] == pytest.approx(21600 * (1 + IVA))
    assert p["utilidad"] == pytest.approx(3600)
