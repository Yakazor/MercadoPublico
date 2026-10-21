from datetime import date

from radar.almacenamiento import BaseDatos
from radar.cliente_api import ErrorApi
from radar.config import cargar_config
from radar.filtro import FiltroRubros
from radar.licitaciones import clasificar, radar_licitaciones

FILTRO = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes"]}})


class ClienteFalso:
    def __init__(self, activas, detalles, fallan=()):
        self.activas, self.detalles, self.fallan = activas, detalles, set(fallan)

    def licitaciones(self, estado=None, codigo=None):
        if codigo is None:
            return {"Listado": self.activas}
        if codigo in self.fallan:
            raise ErrorApi("simulado")
        return {"Listado": [self.detalles[codigo]]} if codigo in self.detalles else {"Listado": []}


def _det(codigo, nombre):
    return {"CodigoExterno": codigo, "Nombre": nombre, "Fechas": {"FechaCierre": "2026-10-20T15:00:00"}}


def test_fallidas_se_informan_y_no_se_depuran(tmp_path):
    activas = [{"CodigoExterno": c, "Nombre": f"Compra de guantes {c}"} for c in ("A", "B", "C")]
    cliente = ClienteFalso(activas, {"A": _det("A", "Compra de guantes A")}, fallan={"B"})
    r = radar_licitaciones(cliente, FILTRO, hoy=date(2026, 10, 10))
    assert [f["codigo"] for f in r.filas] == ["A"]
    assert r.fallidas == {"B", "C"}       # B: error de API; C: detalle vacío
    assert r.candidatas == 3

    db = BaseDatos(tmp_path / "r.db")
    db.guardar_licitaciones([{"codigo": c, "nombre": "x", "fecha_cierre": "2026-10-20 15:00:00", "rubro": "aseo"}
                             for c in ("A", "B", "C", "D")])
    eliminadas = db.depurar_vigentes({f["codigo"] for f in r.filas} | r.fallidas, hoy=date(2026, 10, 10))
    assert eliminadas == 1   # solo D, que ya no es candidata
    codigos = {c for (c,) in db.con.execute("SELECT codigo FROM licitaciones")}
    assert codigos == {"A", "B", "C"}


def test_alerta_de_latex_usa_el_producto_onu_de_la_misma_linea():
    filtro = FiltroRubros.desde_config(cargar_config())
    det = {"CodigoExterno": "L", "Nombre": "Adquisición de guantes de nitrilo",
           "Items": {"Listado": [{"NombreProducto": "Guantes de examen de nitrilo",
                                  "Descripcion": "Guante de examen libre de polvo, látex, talla M"}]}}
    fila = clasificar(det, filtro)
    assert fila and fila["alertas_regulatorias"] is None



class ApiLicitaciones:
    def __init__(self, listado, detalles):
        self.listado, self.detalles, self.pedidos = listado, detalles, []

    def licitaciones(self, estado=None, codigo=None):
        if codigo is None:
            return {"Listado": self.listado}
        self.pedidos.append(codigo)
        return {"Listado": [self.detalles[codigo]]}


def test_detalle_guardado_se_reutiliza_hasta_que_cambie_el_cierre(tmp_path):
    filtro = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes"]}})
    db = BaseDatos(tmp_path / "r.db")
    det = {"CodigoExterno": "A", "Nombre": "Compra de guantes", "Fechas": {"FechaCierre": "2026-10-20T15:00:00"}}
    api = ApiLicitaciones([{"CodigoExterno": "A", "Nombre": "Compra de guantes", "FechaCierre": "2026-10-20T15:00:00"}],
                          {"A": det})
    r = radar_licitaciones(api, filtro, db=db, hoy=date(2026, 10, 13))
    assert (r.descargadas, r.reutilizadas, len(r.filas)) == (1, 0, 1)
    r = radar_licitaciones(api, filtro, db=db, hoy=date(2026, 10, 14))
    assert (r.descargadas, r.reutilizadas, len(r.filas)) == (0, 1, 1) and api.pedidos == ["A"]
    # Cambió la fecha de cierre en el listado: se vuelve a pedir.
    api.listado[0]["FechaCierre"] = "2026-10-27T15:00:00"
    assert radar_licitaciones(api, filtro, db=db, hoy=date(2026, 10, 15)).descargadas == 1
    # Pasaron los días de refresco: se vuelve a pedir.
    assert radar_licitaciones(api, filtro, db=db, hoy=date(2026, 10, 25), refrescar_dias=7).descargadas == 1
    assert db.podar_detalles_licitacion(set()) == 1


def test_clasificar_revisa_el_producto_onu_de_cada_linea():
    detalle = {"CodigoExterno": "1-1-LE26", "Nombre": "Convenio de Suministro de Balones Vasculares",
               "Items": {"Listado": [{"Correlativo": 1, "NombreProducto": "Juegos o catéteres introductores vasculares",
                                      "Descripcion": "Balón de angioplastia 3 mm"}]}}
    assert clasificar(detalle, FiltroRubros.desde_config(cargar_config()), date(2026, 10, 21)) is None
