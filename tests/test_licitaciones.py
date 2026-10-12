from datetime import date

from radar.almacenamiento import BaseDatos
from radar.cliente_api import ErrorApi
from radar.filtro import FiltroRubros
from radar.licitaciones import radar_licitaciones

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
