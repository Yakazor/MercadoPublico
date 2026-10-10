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


# Forma real devuelta por licitaciones.json?codigo=1000-24-LE26 (10-10-2026, resumida)
DETALLE_REAL = {
    "CodigoExterno": "1000-24-LE26",
    "Nombre": "SUM. DE PIEZAS DE MADERA DE ROBLE O COIGÜE",
    "CodigoEstado": 5,
    "Descripcion": "La Dirección Provincial de Vialidad, Provincia de Biobío, necesita adquirir...",
    "FechaCierre": None,
    "Estado": "Publicada",
    "Comprador": {
        "NombreOrganismo": "MINISTERIO DE OBRAS PUBLICAS DIREC CION GRAL DE OO PP DCYF",
        "NombreUnidad": "Dirección de Vialidad - VIII Región - Provincia Bio Bio",
        "ComunaUnidad": "Los Angeles",
        "RegionUnidad": "Región del Biobío ",
    },
    "Tipo": "LE",
    "Moneda": "CLP",
    "Fechas": {
        "FechaCreacion": "2026-09-28T11:36:56.01",
        "FechaCierre": "2026-10-16T15:10:00",
        "FechaPublicacion": "2026-10-06T17:51:21.567",
    },
    "VisibilidadMonto": 0,
    "MontoEstimado": None,
    "Items": {"Cantidad": 2, "Listado": [{
        "Correlativo": 1,
        "Categoria": "Productos derivados de minerales, plantas y animales",
        "NombreProducto": "Maderas duras",
        "Descripcion": "PIEZAS DE MADERA DE ROBLE O COIGUE",
        "UnidadMedida": "Unidad",
        "Cantidad": 780.0,
    }]},
}


def test_detalle_real_de_la_api():
    filtro = FiltroRubros({"madera": {"nombre": "Madera", "palabras_clave": ["maderas duras"]}})
    r = filtro.evaluar(*texto_licitacion(DETALLE_REAL))
    f = fila_licitacion(DETALLE_REAL, r, hoy=date(2026, 10, 10))
    assert f["region"] == "Región del Biobío"
    assert f["fecha_cierre"] == "2026-10-16 15:10:00"
    assert f["fecha_publicacion"] == "2026-10-06 17:51:21.567000"
    assert f["monto_estimado"] is None
    assert f["estado"] == "Publicada"
    assert f["dias_restantes"] == 6
    assert f["rubro"] == "madera"


# Forma real devuelta por ordenesdecompra.json?codigo=1000813-117-AG26 (resumida)
OC_REAL = {
    "Codigo": "1000813-117-AG26",
    "Nombre": "LP_ ADQUISICION DE MATERIALES PARA MANTENIMIENTO Y REPARACION",
    "CodigoEstado": 12,
    "Estado": "Recepción Conforme",
    "CodigoLicitacion": "",
    "TipoMoneda": "CLP",
    "Fechas": {"FechaCreacion": "2026-04-20T10:28:25.683"},
    "TotalNeto": 936676.0,
    "Comprador": {
        "NombreOrganismo": "DIVISION LOGISTICA DEL EJERCITO",
        "RegionUnidad": "Región de Magallanes y de la Antártica",
    },
    "Proveedor": {"Nombre": "VIOLETA DEL CARMEN ", "RutSucursal": "76.490.442-7"},
    "Items": {"Cantidad": 1, "Listado": [{
        "Correlativo": 1,
        "Categoria": "Artículos de fabricación y producción / Pinturas, diluyentes y accesorios",
        "Producto": "Brochas",
        "EspecificacionComprador": 'BROCHA CERDA HELA DE 3"',
        "EspecificacionProveedor": 'BROCHA CERDA HELA DE 3"',
        "Cantidad": 8.0,
        "Unidad": None,
        "Moneda": "CLP",
        "PrecioNeto": 4516.0,
        "Total": 0.0,
    }]},
}


def test_orden_compra_real_recalcula_total_y_limpia_textos():
    f = filas_orden_compra(OC_REAL, FILTRO.evaluar(""))[0]
    assert f["proveedor"] == "VIOLETA DEL CARMEN"
    assert f["precio_unitario_neto"] == 4516.0
    assert f["total_item"] == 8 * 4516.0
    assert f["fecha_creacion"] == "2026-04-20 10:28:25.683000"
    assert f["region"] == "Región de Magallanes y de la Antártica"
