from datetime import date

from radar.filtro import FiltroRubros
from radar.config import cargar_config
from radar.modelos import fila_licitacion, filas_orden_compra, textos_licitacion

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


def _evaluar(filtro, detalle):
    descripcion, items, onu = textos_licitacion(detalle)
    return filtro.evaluar(*descripcion, nombre=detalle["Nombre"], items=items, items_onu=onu)


def test_fila_licitacion_campos_minimos():
    r = _evaluar(FILTRO, DETALLE)
    f = fila_licitacion(DETALLE, r, hoy=date(2026, 10, 10))
    assert f["codigo"] == "1234-56-LE26"
    assert f["organismo"] == "Hospital X"
    assert f["region"] == "Región de Valparaíso"
    assert f["monto_estimado"] == 1500000.0
    assert f["estado"] == "Publicada"
    assert f["rubro"] == "aseo"
    assert f["dias_restantes"] == 10
    assert f["alertas_regulatorias"] is None and f["solo_regulados"] == 0


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
    filtro = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "mascarillas"]}})
    filas = filas_orden_compra(oc, filtro)
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
    r = _evaluar(filtro, DETALLE_REAL)
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
    filtro = FiltroRubros({"pinturas": {"nombre": "Pinturas", "palabras_clave": ["brocha"]}})
    f = filas_orden_compra(OC_REAL | {"Nombre": "Compra de brochas"}, filtro)[0]
    assert f["proveedor"] == "VIOLETA DEL CARMEN"
    assert f["precio_unitario_neto"] == 4516.0
    assert f["total_item"] == 8 * 4516.0
    assert f["fecha_creacion"] == "2026-04-20 10:28:25.683000"
    assert f["region"] == "Región de Magallanes y de la Antártica"


def test_orden_compra_guarda_solo_items_del_rubro_con_config_real():
    """Caso visto en la corrida real del 12-10-2026: OC de 'insumos clínicos' con
    monitores y sondas, y OC de consultoría con catering y pasajes."""
    filtro = FiltroRubros.desde_config(cargar_config())
    oc = {
        "Codigo": "OC-X", "Nombre": "Adquisición de insumos clínicos para pabellón", "TipoMoneda": "CLP",
        "Items": {"Listado": [
            {"Correlativo": 1, "Producto": "Guantes médicos de examen", "Cantidad": 10, "PrecioNeto": 3000},
            {"Correlativo": 2, "Producto": "Sonda Foley", "Cantidad": 5, "PrecioNeto": 2000},
            {"Correlativo": 3, "Producto": "Monitor multiparámetro", "Cantidad": 1, "PrecioNeto": 9000000},
            {"Correlativo": 4, "Producto": "Alcohol gel 1 litro", "Cantidad": 20, "PrecioNeto": 2500},
        ]},
    }
    filas = filas_orden_compra(oc, filtro)
    assert [f["correlativo"] for f in filas] == [1, 4]
    assert filas[0]["rubro"] == "insumos_medicos_aseo" and filas[0]["alertas_regulatorias"] is None
    assert "Alcohol gel" in filas[1]["alertas_regulatorias"]

    consultoria = {
        "Codigo": "OC-Y", "Nombre": "Asesoría en gestión estratégica", "TipoMoneda": "CLP",
        "Items": {"Listado": [
            {"Correlativo": 1, "Producto": "Asesorías en gestión estratégica", "Cantidad": 1, "PrecioNeto": 1144125},
            {"Correlativo": 2, "Producto": "Servicios de catering", "Cantidad": 1, "PrecioNeto": 280000},
            {"Correlativo": 3, "Producto": "Pasaje aéreo nacional", "Cantidad": 1, "PrecioNeto": 128516},
        ]},
    }
    filas = filas_orden_compra(consultoria, filtro)
    assert [f["producto"] for f in filas] == ["Asesorías en gestión estratégica"]
    assert filas[0]["rubro"] == "consultoria_gestion_bi"


def test_alertas_regulatorias_en_licitacion():
    filtro = FiltroRubros.desde_config(cargar_config())
    det = {"CodigoExterno": "A", "Nombre": "CONV SUMINISTRO ALCOHOL GEL PARA 24 MESES", "Items": {"Listado": []}}
    r = _evaluar(filtro, det)
    f = fila_licitacion(det, r, alertas=filtro.alertas(det["Nombre"]), solo_regulados=r.solo_regulados)
    assert "Alcohol gel" in f["alertas_regulatorias"] and f["solo_regulados"] == 1

    det = {"CodigoExterno": "B", "Nombre": "Suministro de papel higiénico y toallas de papel"}
    r = _evaluar(filtro, det)
    assert r.coincide and filtro.alertas(det["Nombre"]) == [] and not r.solo_regulados


def test_orden_compra_items_genericos_usan_nombre_de_la_oc():
    filtro = FiltroRubros.desde_config(cargar_config())
    oc = {"Codigo": "OC-G", "Nombre": "Compra de guantes de nitrilo", "TipoMoneda": "CLP",
          "Items": {"Listado": [
              {"Correlativo": 1, "Producto": "NITRIDERM TALLA M CAJA 100", "Cantidad": 10, "PrecioNeto": 5000},
              {"Correlativo": 2, "Producto": "Sonda Foley", "Cantidad": 1, "PrecioNeto": 2000},
          ]}}
    filas = filas_orden_compra(oc, filtro)
    assert [f["correlativo"] for f in filas] == [1]   # la sonda sigue excluida


def test_orden_compra_especificaciones_no_detectan_ni_excluyen():
    filtro = FiltroRubros.desde_config(cargar_config())
    oc = {"Codigo": "OC-S", "Nombre": "Adquisición de insumos clínicos para pabellón", "TipoMoneda": "CLP",
          "Items": {"Listado": [
              {"Correlativo": 1, "Producto": "Monitor multiparámetro",
               "EspecificacionComprador": "Insumos médicos para pabellón según bases", "PrecioNeto": 9000000},
              {"Correlativo": 2, "Producto": "Sonda Foley 2 vías",
               "EspecificacionProveedor": "Producto sellado; manipular con guantes", "PrecioNeto": 2000},
              {"Correlativo": 3, "Producto": "Alcohol gel 1 lt",
               "Categoria": "Medicamentos y productos farmacéuticos / Antiinfecciosos / Antisépticos",
               "PrecioNeto": 2500},
          ]}}
    filas = filas_orden_compra(oc, filtro)
    assert [f["correlativo"] for f in filas] == [3]


def test_consultoria_no_usa_categoria_onu_pero_insumos_si():
    """Corrida real 12-10-2026: 'Servicios profesionales médicos anestesiólogos' salía como
    BI por la categoría ONU 'Servicios de consultoría de gestión'."""
    filtro = FiltroRubros.desde_config(cargar_config())
    medicos = {"CodigoExterno": "M", "Nombre": "Servicios de Profesionales médicos Anestesiólogos",
               "Items": {"Listado": [{"NombreProducto": "Servicios de consultoría de gestión",
                                      "Categoria": "Servicios de gestión / Consultorías de gestión",
                                      "Descripcion": "Turnos de anestesia"}]}}
    assert not _evaluar(filtro, medicos).coincide
    bi = medicos | {"Nombre": "Servicios profesionales",
                    "Items": {"Listado": [{"Categoria": "Servicios de gestión",
                                           "Descripcion": "Desarrollo de dashboards en Power BI"}]}}
    assert _evaluar(filtro, bi).rubro == "consultoria_gestion_bi"
    guantes = {"CodigoExterno": "G", "Nombre": "Insumos clínicos varios",
               "Items": {"Listado": [{"NombreProducto": "Guantes médicos de examen", "Descripcion": "talla M"}]}}
    assert _evaluar(filtro, guantes).rubro == "insumos_medicos_aseo"


def test_medicamento_inyectable_en_jeringa_no_es_insumo():
    filtro = FiltroRubros.desde_config(cargar_config())
    assert not filtro.es_candidata("C.S. de Paliperidona 75 mg Susp. Iny. LP Jeringa P")
