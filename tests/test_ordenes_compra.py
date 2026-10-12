import pandas as pd

from radar.ordenes_compra import resumen_precios


def test_resumen_precios_agrupa_por_producto_normalizado():
    items = pd.DataFrame([
        {"rubro_nombre": "Aseo", "producto": "Guantes Nitrilo", "unidad": "Caja", "moneda": "CLP", "estado": "Aceptada",
         "codigo_oc": "1", "proveedor": "A", "cantidad": 10, "precio_unitario_neto": 100, "total_item": 1000},
        {"rubro_nombre": "Aseo", "producto": "guantes nitrilo", "unidad": "Caja", "moneda": "CLP", "estado": "Aceptada",
         "codigo_oc": "2", "proveedor": "B", "cantidad": 5, "precio_unitario_neto": 300, "total_item": 1500},
        {"rubro_nombre": "Aseo", "producto": "Cloro", "unidad": "Litro", "moneda": "CLP", "estado": "Aceptada",
         "codigo_oc": "2", "proveedor": "B", "cantidad": 1, "precio_unitario_neto": 0, "total_item": 0},
    ])
    r = resumen_precios(items)
    assert len(r) == 1
    fila = r.iloc[0]
    assert fila["n_ordenes"] == 2 and fila["precio_mediana"] == 200 and fila["cantidad_total"] == 15


def test_resumen_precios_excluye_oc_canceladas():
    base = {"rubro_nombre": "Aseo", "producto": "Cloro", "unidad": "Litro", "moneda": "CLP", "estado": "Aceptada",
            "proveedor": "A", "cantidad": 1, "total_item": 0}
    items = pd.DataFrame([
        base | {"codigo_oc": "1", "estado": "Recepción Conforme", "precio_unitario_neto": 1000},
        base | {"codigo_oc": "2", "estado": "Cancelada", "precio_unitario_neto": 99999},
    ])
    r = resumen_precios(items)
    assert r.iloc[0]["n_ordenes"] == 1 and r.iloc[0]["precio_max"] == 1000


# --- Procesamiento por día con un cliente simulado ------------------------------
from datetime import date

from radar.almacenamiento import BaseDatos
from radar.cliente_api import ErrorApi
from radar.filtro import FiltroRubros
from radar.ordenes_compra import COLUMNAS_RESUMEN, procesar_dia, reclasificar_items

FILTRO = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "cloro"],
                                "excluir_en_nombre_salvo_clave": ["sonda"]}})


class ClienteFalso:
    def __init__(self, listado, detalles, fallan=()):
        self.listado, self.detalles, self.fallan = listado, detalles, set(fallan)

    def ordenes_de_compra(self, fecha=None, estado=None, codigo=None):
        if codigo is None:
            return {"Listado": self.listado}
        if codigo in self.fallan:
            raise ErrorApi("simulado")
        return {"Listado": [self.detalles[codigo]]}


def _oc(codigo, *productos):
    return {"Codigo": codigo, "Nombre": f"Compra de guantes {codigo}", "Estado": "Aceptada", "TipoMoneda": "CLP",
            "Items": {"Listado": [{"Correlativo": i, "Producto": p, "Cantidad": 1, "PrecioNeto": 100}
                                  for i, p in enumerate(productos, 1)]}}


def test_procesar_dia_cuenta_fallidas_y_no_completa(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    listado = [{"Codigo": "A", "Nombre": "Compra de guantes A"}, {"Codigo": "B", "Nombre": "Compra de guantes B"}]
    cliente = ClienteFalso(listado, {"A": _oc("A", "Guantes nitrilo", "Sonda Foley")}, fallan={"B"})
    r = procesar_dia(cliente, FILTRO, db, date(2026, 10, 5))
    assert (r.items, r.ordenes, r.fallidas, r.completo) == (1, 1, 1, False)
    assert list(db.items_oc()["producto"]) == ["Guantes nitrilo"]


def test_reprocesar_oc_reemplaza_items(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    listado = [{"Codigo": "A", "Nombre": "Compra de guantes A"}]
    procesar_dia(ClienteFalso(listado, {"A": _oc("A", "Guantes", "Cloro")}), FILTRO, db, date(2026, 10, 5))
    assert len(db.items_oc()) == 2
    # La OC ya no trae cloro: el ítem viejo se borra.
    procesar_dia(ClienteFalso(listado, {"A": _oc("A", "Guantes")}), FILTRO, db, date(2026, 10, 6))
    assert list(db.items_oc()["producto"]) == ["Guantes"]


def test_reclasificar_items_con_config_nueva(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    amplio = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "catering"]}})
    procesar_dia(ClienteFalso([{"Codigo": "A", "Nombre": "Compra de guantes"}],
                              {"A": _oc("A", "Guantes", "Servicios de catering")}), amplio, db, date(2026, 10, 5))
    assert len(db.items_oc()) == 2
    actualizados, eliminados = reclasificar_items(db, FILTRO)
    assert (actualizados, eliminados) == (1, 1)
    assert list(db.items_oc()["producto"]) == ["Guantes"]


def test_resumen_vacio_tiene_columnas_del_resumen():
    vacio = resumen_precios(pd.DataFrame())
    assert vacio.empty and list(vacio.columns) == COLUMNAS_RESUMEN


def test_resumen_une_alertas_por_producto():
    base = {"rubro_nombre": "Aseo", "producto": "Cloro", "unidad": None, "moneda": "CLP", "estado": "Aceptada",
            "proveedor": "A", "cantidad": 1, "total_item": 100, "precio_unitario_neto": 100}
    items = pd.DataFrame([base | {"codigo_oc": "1", "alertas_regulatorias": "Desinfectantes/cloro: registro"},
                          base | {"codigo_oc": "2", "alertas_regulatorias": None}])
    r = resumen_precios(items)
    assert r.iloc[0]["alertas_regulatorias"] == "Desinfectantes/cloro: registro"
