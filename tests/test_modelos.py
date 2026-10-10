from datetime import date

from radar.filtro import FiltroRubros
from radar.modelos import fila_licitacion, filas_orden_compra, texto_licitacion

FILTRO = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes"]}})

DETALLE = {
    "CodigoExterno": "1234-56-LE26",
    "Nombre": "Compra de insumos",
    "CodigoEstado": 5,
    "Comprador": {"NombreOrganismo": "Hospital X", "RegionUnidad": "Región de Valparaíso "},
    "MontoEstimado": 1500000,
    "Fechas": {"FechaPublicacion": "2026-10-01T10:00:00", "FechaCierre": "2026-10-20T15:00:00"},
    "Items": {"Listado": [{"NombreProducto": "Guantes de nitrilo", "Descripcion": "talla M"}]},
}


def test_fila_licitacion_campos_minimos():
    r = FILTRO.evaluar(*texto_licitacion(DETALLE))
    f = fila_licitacion(DETALLE, r, hoy=date(2026, 10, 10))
    assert f["codigo"] == "1234-56-LE26"
    assert f["organismo"] == "Hospital X"
    assert f["region"] == "Región de Valparaíso"
    assert f["monto_estimado"] == 1500000.0
    assert f["estado"] == "Publicada"
    assert f["rubro"] == "aseo"
    assert f["dias_restantes"] == 10


def test_fila_tolera_campos_faltantes():
    f = fila_licitacion({"CodigoExterno": "X"}, FILTRO.evaluar(""))
    assert f["monto_estimado"] is None and f["dias_restantes"] is None


def test_orden_compra_una_fila_por_item():
    oc = {
        "Codigo": "OC-1",
        "Items": {"Listado": [
            {"Producto": "Guantes", "Cantidad": 100, "PrecioNeto": 50},
            {"Producto": "Mascarillas", "Cantidad": "10", "PrecioNeto": "20.5"},
        ]},
    }
    filas = filas_orden_compra(oc, FILTRO.evaluar("guantes"))
    assert [f["precio_unitario_neto"] for f in filas] == [50.0, 20.5]
