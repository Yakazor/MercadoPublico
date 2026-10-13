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
            raise ErrorApi("simulado", temporal=True)
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
    assert (r.items, r.ordenes, r.fallidas, r.completo) == (1, 1, ["B"], False)
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
    assert reclasificar_items(db, FILTRO) == (1, 1, 0)
    assert list(db.items_oc()["producto"]) == ["Guantes"]


def test_reclasificar_agrega_items_que_ahora_son_del_rubro(tmp_path):
    """El detalle de la OC queda guardado: al ampliar las palabras clave, los ítems
    descartados en la descarga se recuperan sin volver a llamar a la API."""
    db = BaseDatos(tmp_path / "r.db")
    procesar_dia(ClienteFalso([{"Codigo": "A", "Nombre": "Compra de guantes"}],
                              {"A": _oc("A", "Guantes", "Escobas")}), FILTRO, db, date(2026, 10, 5))
    assert list(db.items_oc()["producto"]) == ["Guantes"]
    amplio = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "escobas"]}})
    assert reclasificar_items(db, amplio) == (1, 0, 1)
    assert sorted(db.items_oc()["producto"]) == ["Escobas", "Guantes"]
    # Y vuelve a quitarlos con la config anterior, sin perder el detalle.
    assert reclasificar_items(db, FILTRO) == (1, 1, 0)
    assert reclasificar_items(db, amplio) == (1, 0, 1)


def test_reclasificar_oc_antigua_sin_detalle(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    base = {"codigo_oc": "V", "nombre_oc": "Compra de guantes", "rubro": "aseo"}
    db.reemplazar_items_oc("V", [base | {"correlativo": 1, "producto": "Guantes"},
                                 base | {"correlativo": 2, "producto": "Catering"}])
    assert reclasificar_items(db, FILTRO) == (1, 1, 0)
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


def test_reclasificar_purga_oc_cuyo_nombre_quedo_excluido(tmp_path):
    from radar.config import cargar_config
    db = BaseDatos(tmp_path / "r.db")
    sin_exclusiones = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes"]}})
    oc = _oc("A", "Guante cabritilla") | {"Nombre": "Guantes de cuero para soldador"}
    procesar_dia(ClienteFalso([{"Codigo": "A", "Nombre": oc["Nombre"]}], {"A": oc}), sin_exclusiones, db,
                 date(2026, 10, 5))
    assert len(db.items_oc()) == 1
    assert reclasificar_items(db, FiltroRubros.desde_config(cargar_config())) == (0, 1, 0)
    assert db.items_oc().empty


def test_procesar_dia_purga_oc_que_dejo_de_ser_candidata(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    amplio = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "cuero"]}})
    listado = [{"Codigo": "A", "Nombre": "Compra de cuero"}]
    procesar_dia(ClienteFalso(listado, {"A": _oc("A", "Cuero") | {"Nombre": "Compra de cuero"}}), amplio, db,
                 date(2026, 10, 5))
    assert len(db.items_oc()) == 1
    r = procesar_dia(ClienteFalso(listado, {}), FILTRO, db, date(2026, 10, 5))
    assert r.purgadas == 1 and db.items_oc().empty


def test_procesar_dia_respeta_tiempo_limite(tmp_path):
    import time
    db = BaseDatos(tmp_path / "r.db")
    listado = [{"Codigo": "A", "Nombre": "Compra de guantes A"}]
    r = procesar_dia(ClienteFalso(listado, {"A": _oc("A", "Guantes")}), FILTRO, db, date(2026, 10, 5),
                     hasta_monotonic=time.monotonic() - 1)
    assert r.interrumpido and not r.completo and r.items == 0


def test_intentos_fallidos_se_acumulan(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    assert db.registrar_intento_fallido(date(2026, 10, 5), ["X"]) == 1
    assert db.registrar_intento_fallido(date(2026, 10, 5), ["X"]) == 2


class ClienteConErrores(ClienteFalso):
    def __init__(self, listado, detalles, definitivas=(), temporales=()):
        super().__init__(listado, detalles)
        self.definitivas, self.temporales = set(definitivas), set(temporales)

    def ordenes_de_compra(self, fecha=None, estado=None, codigo=None):
        if codigo in self.definitivas:
            raise ErrorApi("Código no válido", temporal=False)
        if codigo in self.temporales:
            raise ErrorApi("HTTP 500 tras reintentos", temporal=True)
        return super().ordenes_de_compra(fecha, estado, codigo)


def test_error_definitivo_no_deja_el_dia_pendiente(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    listado = [{"Codigo": "A", "Nombre": "Compra de guantes A"}, {"Codigo": "B", "Nombre": "Compra de guantes B"}]
    r = procesar_dia(ClienteConErrores(listado, {"A": _oc("A", "Guantes")}, definitivas={"B"}),
                     FILTRO, db, date(2026, 10, 5))
    assert r.completo and r.fallidas == []
    r = procesar_dia(ClienteConErrores(listado, {"A": _oc("A", "Guantes")}, temporales={"B"}),
                     FILTRO, db, date(2026, 10, 6))
    assert not r.completo and r.fallidas == ["B"]


def test_dias_pendientes(tmp_path):
    db = BaseDatos(tmp_path / "r.db")
    db.registrar_intento_fallido(date(2026, 9, 5), ["X"])
    db.registrar_intento_fallido(date(2026, 9, 6), ["Y"])
    db.marcar_dia_oc(date(2026, 9, 6))
    assert db.dias_pendientes() == [date(2026, 9, 5)]
