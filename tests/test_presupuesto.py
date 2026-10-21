import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from radar.modelos import VERSION_DETALLE_LICITACION, compactar_licitacion
from radar.presupuesto import (IVA, ReferenciasOC, armar_presupuesto, items_licitacion_presupuesto,
                               referencia_comparable, unidad_global)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import presupuesto as script  # noqa: E402

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


def test_prefiere_producto_equivalente_a_uno_aproximado_mas_barato():
    items = [{"linea": 1, "cantidad": 1}]
    mercado = [
        {"linea": 1, "tienda": "Otra marca", "precio_unitario_neto": 500, "coincidencia": "aproximada"},
        {"linea": 1, "tienda": "Igual", "precio_unitario_neto": 800, "coincidencia": "exacta"},
    ]
    assert armar_presupuesto(items, mercado)["items"][0]["tienda"] == "Igual"
    solo_aprox = [mercado[0]]
    assert armar_presupuesto(items, solo_aprox)["items"][0]["tienda"] == "Otra marca"


@pytest.mark.parametrize("producto,descripcion", [
    ("Catéteres intravenosos periféricos para uso general", "025-1044 CATETER VENOSO PERIFERICO 20 G"),
    ("Notas de papel autoadhesivo", "Nota adhesiva amarillo fluor, 100 hojas"),
    ("Lijadoras", "LIJADORA BANDA uso general"),
])
def test_referencia_parecida_exige_casi_todas_las_palabras(producto, descripcion):
    precios = pd.DataFrame([
        {"rubro": "insumos_medicos_aseo", "producto_normalizado": "limpiadores de uso general", "moneda": "CLP",
         "precio_mediana": 3710.0, "precio_p25": 3000.0, "n_ordenes": 5},
        {"rubro": "oficina_libreria", "producto_normalizado": "papel de manualidades autoadhesivo", "moneda": "CLP",
         "precio_mediana": 4890.0, "precio_p25": 4000.0, "n_ordenes": 5},
    ])
    assert ReferenciasOC(precios).buscar(producto, descripcion) is None


def test_ignora_opciones_descartadas():
    items = [{"linea": 1, "cantidad": 2}, {"linea": 2, "cantidad": 1}]
    mercado = [
        {"linea": 1, "tienda": "Barata", "precio_unitario_neto": 100, "coincidencia": "exacta",
         "descartado": True, "motivo_descarte": "precio de otra presentación"},
        {"linea": 1, "tienda": "Buena", "precio_unitario_neto": 300, "coincidencia": "exacta"},
        {"linea": 2, "tienda": "Única", "precio_unitario_neto": 50, "descartado": True},
    ]
    p = armar_presupuesto(items, mercado, margen=0.0, otros_costos=0.0)
    assert p["items"][0]["tienda"] == "Buena"
    # Si todas las opciones de la línea están descartadas, queda sin precio.
    assert p["items"][1]["tienda"] is None and p["items_sin_precio"] == 1
    assert p["costo_neto"] == pytest.approx(600)


@pytest.mark.parametrize("ref,costo,esperado", [
    (100, 1000, True), (10000, 1000, True), (99, 1000, False), (10001, 1000, False),
    (None, 1000, None), (500, None, None),
])
def test_referencia_comparable_entre_un_decimo_y_diez_veces(ref, costo, esperado):
    assert referencia_comparable(ref, costo) is esperado


def test_referencia_oc_no_comparable_no_entra_en_los_totales():
    items = [
        {"linea": 1, "cantidad": 30, "unidad": "Unidad", "ref_mediana": 1790250.0},  # 61 veces el costo
        {"linea": 2, "cantidad": 10, "unidad": "Unidad", "ref_mediana": 20.0},       # 50 veces menor
        {"linea": 3, "cantidad": 40, "unidad": "Unidad", "ref_mediana": 61100.0},    # 4,6 veces: se compara
        {"linea": 4, "cantidad": 1, "unidad": "Unidad", "ref_mediana": 5000.0},      # sin precio de mercado
    ]
    mercado = [
        {"linea": 1, "precio_unitario_neto": 27722.69},
        {"linea": 2, "precio_unitario_neto": 1000},
        {"linea": 3, "precio_unitario_neto": 12596.64},
    ]
    p = armar_presupuesto(items, mercado, margen=0.2, otros_costos=0.05)
    assert [i["referencia_comparable"] for i in p["items"]] == [False, False, True, None]
    assert p["items"][0]["margen_vs_referencia"] is None
    assert p["items"][2]["margen_vs_referencia"] == pytest.approx(61100 / (12596.64 * 1.05) - 1)
    assert p["referencia_oc_neta"] == pytest.approx(61100 * 40)
    assert p["oferta_con_referencia"] == pytest.approx(12596.64 * 1.05 * 1.2 * 40)


@pytest.mark.parametrize("unidad,esperado", [
    ("Global", True), ("Kit", True), ("SERVICIO", True), ("Lote ", True),
    ("Unidad", False), ("kilogramo", False), (None, False),
])
def test_unidad_global(unidad, esperado):
    assert unidad_global(unidad) is esperado


def test_lineas_globales_y_opciones_sin_verificar():
    items = [
        {"linea": 1, "cantidad": 1, "unidad": "Global"},
        {"linea": 2, "cantidad": 3, "unidad": "Unidad"},
        {"linea": 3, "cantidad": 1, "unidad": "Servicio"},  # sin precio: no cuenta
        {"linea": 4, "cantidad": 2, "unidad": "Lote"},
    ]
    mercado = [
        {"linea": 1, "precio_unitario_neto": 1000, "verificado": True},
        {"linea": 2, "precio_unitario_neto": 500, "verificado": False},
        {"linea": 4, "precio_unitario_neto": 700, "verificado": True},
    ]
    p = armar_presupuesto(items, mercado)
    assert p["lineas_globales"] == [1, 4]
    assert [i["unidad_global"] for i in p["items"]] == [True, False, True, True]
    assert p["items_sin_verificar"] == 1
    assert p["items"][1]["verificado"] is False and p["items"][2]["verificado"] is None


# --- scripts/presupuesto.py ---

MERCADO = {
    "codigo": "1-1-LE26", "nombre": "Toldos y kits", "fecha_consulta": "2026-10-18",
    "items": [
        {"linea": 1, "producto": "Toldos", "opciones": [
            {"tienda": "Mala", "producto_mercado": "Toldo de juguete", "url": "https://mala.cl/t", "precio": 1190,
             "iva_incluido": True, "precio_unitario_neto": 1000, "coincidencia": "exacta",
             "descartado": True, "motivo_descarte": "es un toldo de juguete"},
            {"tienda": "Sodimac", "producto_mercado": "Toldo plegable 3x3", "url": "https://sodimac.cl/t", "precio": 32990,
             "iva_incluido": True, "precio_unitario_neto": 27722.69, "coincidencia": "aproximada",
             "verificado": True, "verificado_en": "2026-10-20"},
        ]},
        {"linea": 2, "producto": "Kit de aseo", "opciones": [
            {"tienda": "Lider", "producto_mercado": "Kit de aseo", "url": "https://lider.cl/k", "precio": 5950,
             "iva_incluido": True, "precio_unitario_neto": 5000, "coincidencia": "equivalente", "verificado": False,
             "verificacion_pagina": "2026-10-20: la tienda respondió HTTP 403."},
        ]},
        {"linea": 3, "producto": "Sillas", "opciones": []},
    ],
}
ITEMS = [
    {"codigo": "1-1-LE26", "linea": 1, "producto": "Toldos", "cantidad": 30, "unidad": "Unidad", "ref_mediana": 1790250.0},
    {"codigo": "1-1-LE26", "linea": 2, "producto": "Kit de aseo", "cantidad": 1, "unidad": "Kit", "ref_mediana": 6000.0},
    {"codigo": "1-1-LE26", "linea": 3, "producto": "Sillas", "cantidad": 40, "unidad": "Unidad", "ref_mediana": 61100.0},
]


def test_opciones_mercado_marca_descartadas_y_el_dashboard_no_las_recibe():
    opciones = script.opciones_mercado(MERCADO)
    assert opciones[0]["descartado"] is True and opciones[0]["motivo_descarte"] == "es un toldo de juguete"
    assert opciones[1]["descartado"] is False and opciones[1]["motivo_descarte"] is None
    dashboard = script.opciones_dashboard(opciones)
    assert [o["tienda"] for o in dashboard] == ["Sodimac", "Lider"]
    assert "descartado" not in dashboard[0] and "motivo_descarte" not in dashboard[0]
    # La clave numera todas las opciones: no cambia al descartar una.
    assert dashboard[0]["clave"] == "1-1-LE26|1|2"


def test_markdown_descartadas_unidad_global_y_referencia_no_comparable():
    p = armar_presupuesto(ITEMS, script.opciones_mercado(MERCADO))
    md = script.markdown({"codigo": "1-1-LE26", "nombre": "Toldos y kits"}, MERCADO, p)
    filas = md.splitlines()
    # La descartada (más barata) no es el mejor precio y aparece al final de su línea.
    toldo = next(f for f in filas if f.startswith("| 1 | Toldos"))
    assert "Sodimac" in toldo and "$1.790.250 (no comparable)" in toldo
    opciones_toldo = [f for f in filas if f.startswith("| 1 | [")]
    assert "Sodimac" in opciones_toldo[0]
    assert "Mala" in opciones_toldo[1] and opciones_toldo[1].endswith("| descartada: es un toldo de juguete |")
    kit = next(f for f in filas if f.startswith("| 2 | Kit de aseo"))
    assert "no comparable" not in kit
    # Solo el kit (referencia comparable) entra en lo que pagó el Estado.
    assert "| Lo que el Estado pagó en OC por esos ítems (mediana, neto) | $6.000 |" in md
    assert any(f.startswith("> Unidad global en la línea 2 (Kit): la cantidad real está en las bases") for f in filas)
    assert any(f.startswith("> Ref. OC «no comparable» en la línea 1:") for f in filas)


def _p(**cambios):
    return {"items": [{}] * 3, "items_sin_precio": 0, "costo_neto": 1000.0, "oferta_total": 1500.0,
            "utilidad": 200.0, "lineas_globales": [], "items_sin_verificar": 0} | cambios


def test_alertas_del_indice():
    lic = {"codigo": "1-1-LE26", "monto_estimado": 1000, "moneda": "CLP"}
    assert script.alertas(lic, _p()) == ["supera monto"]
    assert script.alertas(lic | {"moneda": "USD"}, _p()) == []
    assert script.alertas(lic | {"monto_estimado": 2000},
                          _p(items_sin_precio=2, lineas_globales=[3], items_sin_verificar=1)) \
        == ["faltan 2 precios", "línea global", "sin verificar"]
    assert script.alertas({}, _p(items_sin_precio=1)) == ["falta 1 precio"]


def test_script_separa_vigentes_y_cerradas(tmp_path, monkeypatch):
    mercado = tmp_path / "mercado"
    mercado.mkdir()
    (mercado / "1-1-LE26.json").write_text(json.dumps(MERCADO), encoding="utf-8")
    (mercado / "9-9-LE26.json").write_text(
        json.dumps({"codigo": "9-9-LE26", "nombre": "Licitación vieja", "items": []}), encoding="utf-8")
    lics = [{"codigo": "1-1-LE26", "nombre": "Toldos y kits", "monto_estimado": 100000, "moneda": "CLP",
             "fecha_cierre": "2026-10-23 15:00:00", "rubro_nombre": "Mobiliario"}]
    (tmp_path / "items.json").write_text(json.dumps(ITEMS), encoding="utf-8")
    (tmp_path / "licitaciones.json").write_text(json.dumps(lics), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "presupuesto.py", "--items", str(tmp_path / "items.json"), "--licitaciones", str(tmp_path / "licitaciones.json"),
        "--mercado", str(mercado), "--salida", str(tmp_path / "p"), "--indice", str(tmp_path / "README.md"),
        "--mercado-json", str(tmp_path / "mercado.json")])
    script.main()

    vigentes, cerradas = (tmp_path / "README.md").read_text(encoding="utf-8").split("## Ya cerradas")
    assert "| Licitación | Rubro | Cierre | Ítems con precio | Costo neto | Oferta total (c/IVA) | Utilidad | " \
           "Monto estimado | Alertas |" in vigentes
    fila = next(f for f in vigentes.splitlines() if f.startswith("| [1-1-LE26]"))
    assert fila.endswith("| $100.000 | supera monto, falta 1 precio, línea global, sin verificar |")
    assert "9-9-LE26" not in vigentes and "ya no vigente" not in vigentes
    assert "- [9-9-LE26](presupuestos/9-9-LE26.md) Licitación vieja" in cerradas
    # El dashboard no recibe las descartadas.
    dashboard = json.loads((tmp_path / "mercado.json").read_text(encoding="utf-8"))
    assert [o["tienda"] for o in dashboard] == ["Sodimac", "Lider"]
    assert (tmp_path / "p" / "1-1-LE26.md").exists() and (tmp_path / "p" / "9-9-LE26.csv").exists()
