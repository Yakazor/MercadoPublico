"""Mapeo del JSON de la API a filas planas (listas para SQLite/Power BI).

IMPORTANTE: los nombres de campo siguen la documentación pública de la API.
Si la respuesta real trae otros nombres, este es el ÚNICO archivo a ajustar.
"""
from __future__ import annotations

from datetime import date, datetime

ESTADOS_LICITACION = {
    5: "Publicada",
    6: "Cerrada",
    7: "Desierta",
    8: "Adjudicada",
    18: "Revocada",
    19: "Suspendida",
}


def _fecha(valor) -> datetime | None:
    if not valor:
        return None
    texto = str(valor).strip()
    for formato in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:26], formato)
        except ValueError:
            continue
    return None


def _numero(valor) -> float | None:
    if valor in (None, ""):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _texto(valor) -> str | None:
    """Recorta espacios (la API devuelve p. ej. "Región del Biobío ")."""
    if valor is None:
        return None
    return str(valor).strip() or None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(sep=" ") if dt else None


def dias_restantes(fecha_cierre: datetime | None, hoy: date | None = None) -> int | None:
    if fecha_cierre is None:
        return None
    return (fecha_cierre.date() - (hoy or date.today())).days


def items_licitacion(detalle: dict) -> list[dict]:
    return (detalle.get("Items") or {}).get("Listado") or []


def textos_licitacion(detalle: dict) -> tuple[list[str], list[str], list[str]]:
    """(descripción, ítems, ítems ONU) para el filtro. El nombre se pasa aparte.

    - ítems: descripción libre de cada línea (lo que escribe el comprador);
    - ítems ONU: producto y categoría del clasificador de Mercado Público, útiles
      para insumos ("Guantes médicos") pero genéricos para servicios ("Servicios
      de consultoría de gestión" se usa para casi cualquier servicio profesional);
    - descripción general: suele mencionar además la unidad solicitante."""
    descripcion = [t for t in [detalle.get("Descripcion")] if t]
    items, onu = [], []
    for item in items_licitacion(detalle):
        items.append(item.get("Descripcion"))
        onu += [item.get("NombreProducto"), item.get("Categoria")]
    return descripcion, [t for t in items if t], [t for t in onu if t]


# Sube cuando cambian los campos guardados: los detalles con otra versión se
# vuelven a pedir (v2: cantidad y unidad de cada ítem, para el presupuesto).
VERSION_DETALLE_LICITACION = 2
_CAMPOS_ITEM_LICITACION = ("Correlativo", "NombreProducto", "Descripcion", "Categoria", "Cantidad", "UnidadMedida")


def compactar_licitacion(detalle: dict) -> dict:
    """Solo los campos que usan el filtro, `fila_licitacion` y el presupuesto: se
    guarda para no volver a pedir cada día el detalle de una licitación ya conocida."""
    comprador = detalle.get("Comprador") or {}
    fechas = detalle.get("Fechas") or {}
    return {
        "_version": VERSION_DETALLE_LICITACION,
        "CodigoExterno": detalle.get("CodigoExterno"),
        "Nombre": detalle.get("Nombre"),
        "Descripcion": detalle.get("Descripcion"),
        "CodigoEstado": detalle.get("CodigoEstado"),
        "Estado": detalle.get("Estado"),
        "MontoEstimado": detalle.get("MontoEstimado"),
        "Moneda": detalle.get("Moneda"),
        "Tipo": detalle.get("Tipo"),
        "FechaCierre": detalle.get("FechaCierre"),
        "Comprador": {k: comprador.get(k) for k in ("NombreOrganismo", "NombreUnidad", "RegionUnidad", "ComunaUnidad")},
        "Fechas": {k: fechas.get(k) for k in ("FechaCierre", "FechaPublicacion")},
        "Items": {"Listado": [{k: item.get(k) for k in _CAMPOS_ITEM_LICITACION}
                              for item in items_licitacion(detalle)]},
    }


def productos_licitacion(detalle: dict) -> list[str]:
    """Cada línea como un producto: producto ONU + lo que escribió el comprador
    ("Guantes de examen de nitrilo" + "libre de polvo, látex, talla M")."""
    lineas = []
    for item in items_licitacion(detalle):
        texto = " ".join(t for t in (item.get("NombreProducto"), item.get("Descripcion")) if t)
        if texto.strip():
            lineas.append(texto)
    return lineas


def fila_licitacion(
    detalle: dict,
    resultado_filtro,
    hoy: date | None = None,
    alertas: list[str] | None = None,
    solo_regulados: bool = False,
) -> dict:
    comprador = detalle.get("Comprador") or {}
    fechas = detalle.get("Fechas") or {}
    cierre = _fecha(fechas.get("FechaCierre") or detalle.get("FechaCierre"))
    codigo_estado = detalle.get("CodigoEstado")
    return {
        "codigo": detalle.get("CodigoExterno"),
        "nombre": detalle.get("Nombre"),
        "organismo": comprador.get("NombreOrganismo"),
        "unidad_compra": comprador.get("NombreUnidad"),
        "region": _texto(comprador.get("RegionUnidad")),
        "comuna": _texto(comprador.get("ComunaUnidad")),
        "monto_estimado": _numero(detalle.get("MontoEstimado")),
        "moneda": detalle.get("Moneda"),
        "tipo": detalle.get("Tipo"),
        "fecha_publicacion": _iso(_fecha(fechas.get("FechaPublicacion"))),
        "fecha_cierre": _iso(cierre),
        "estado": detalle.get("Estado") or ESTADOS_LICITACION.get(codigo_estado),
        "rubro": resultado_filtro.rubro,
        "rubro_nombre": resultado_filtro.rubro_nombre,
        "rubros_todos": ", ".join(resultado_filtro.rubros),
        "palabras_detectadas": ", ".join(resultado_filtro.palabras),
        "dias_restantes": dias_restantes(cierre, hoy),
        "alertas_regulatorias": " | ".join(alertas) if alertas else None,
        "solo_regulados": int(bool(solo_regulados)),
        "url": f"https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion={detalle.get('CodigoExterno')}",
    }


def textos_item_oc(item: dict) -> list[str]:
    return [t for t in (
        item.get("Producto"),
        item.get("EspecificacionComprador"),
        item.get("EspecificacionProveedor"),
        item.get("Categoria"),
    ) if t]


def textos_alerta_item_oc(item: dict) -> list[str]:
    """Para las alertas: producto, lo que pidió el comprador y la categoría (la
    especificación del proveedor trae publicidad del tipo "blanqueado sin cloro")."""
    return [t for t in (item.get("Producto"), item.get("EspecificacionComprador"), item.get("Categoria")) if t]


def clasificar_items_oc(nombre_oc: str | None, items: list[dict], filtro) -> list[tuple[dict, object]]:
    """[(item, Resultado)] de los ítems que pertenecen a un rubro.

    - Si el nombre de la OC está excluido (p. ej. "Guantes de cuero para soldador"
      o "Compra de medicamentos…"), no se guarda nada.
    - Cada ítem se clasifica por su producto/categoría (`filtro.evaluar_item`).
    - Si la OC tiene UN solo ítem sin palabra clave (producto genérico o marca) y
      el nombre de la OC sí la trae, se usa el rubro del nombre ("Compra de guantes
      de nitrilo" con el ítem "NITRIDERM M CAJA 100")."""
    if nombre_oc and not filtro.es_candidata(nombre_oc):
        return []
    evaluados = [
        (item, filtro.evaluar_item(item.get("Producto"), item.get("Categoria"),
                                   item.get("EspecificacionComprador"), item.get("EspecificacionProveedor")))
        for item in items
    ]
    # Respaldo por nombre solo con UN ítem: en OC de varios ítems sin palabra clave,
    # los ítems genéricos pueden ser de otro rubro (pasajes, catering, despacho).
    # Solo en rubros de productos y con un nombre que diga qué producto es: en
    # consultoría una OC "Café para jornada de planificación estratégica" no hace BI
    # al café (ver `FiltroRubros.respaldo_por_nombre`).
    if len(evaluados) == 1 and not evaluados[0][1].coincide and nombre_oc:
        por_nombre = filtro.respaldo_por_nombre(nombre_oc)
        # Solo si el ítem no está excluido en ESE rubro ("bajo impacto ambiental"
        # excluye en consultoría, no en aseo).
        if por_nombre.coincide and por_nombre.rubro not in evaluados[0][1].excluidos:
            evaluados = [(evaluados[0][0], por_nombre)]
    # Servicios: "Servicios de consultoría de gestión" + "según términos de referencia"
    # en una OC "Consultoría en gestión estratégica" toma el rubro del nombre (también
    # con varios ítems: un "Servicio de catering" no es un producto compatible).
    if nombre_oc:
        evaluados = [
            (item, _respaldo_servicio(filtro, nombre_oc, item, r)) if not r.coincide else (item, r)
            for item, r in evaluados
        ]
    return [(item, r) for item, r in evaluados if r.coincide]


def _respaldo_servicio(filtro, nombre_oc: str, item: dict, resultado):
    por_servicio = filtro.respaldo_servicio(nombre_oc, item.get("Producto"), item.get("EspecificacionComprador"))
    if por_servicio.coincide and por_servicio.rubro not in resultado.excluidos:
        return por_servicio
    return resultado


_CAMPOS_ITEM_OC = ("Correlativo", "Producto", "Categoria", "EspecificacionComprador",
                   "EspecificacionProveedor", "Unidad", "Cantidad", "PrecioNeto", "Total")


def compactar_oc(detalle: dict) -> dict:
    """Solo los campos que usa `filas_orden_compra`: se guarda en la base para
    reclasificar con otra config sin volver a descargar la OC."""
    comprador = detalle.get("Comprador") or {}
    proveedor = detalle.get("Proveedor") or {}
    items = (detalle.get("Items") or {}).get("Listado") or []
    return {
        "Codigo": detalle.get("Codigo"),
        "Nombre": detalle.get("Nombre"),
        "CodigoLicitacion": detalle.get("CodigoLicitacion"),
        "Estado": detalle.get("Estado"),
        "TipoMoneda": detalle.get("TipoMoneda"),
        "Fechas": {"FechaCreacion": (detalle.get("Fechas") or {}).get("FechaCreacion")},
        "Comprador": {"NombreOrganismo": comprador.get("NombreOrganismo"),
                      "RegionUnidad": comprador.get("RegionUnidad")},
        "Proveedor": {"Nombre": proveedor.get("Nombre"), "RutSucursal": proveedor.get("RutSucursal")},
        "Items": {"Listado": [{k: item.get(k) for k in _CAMPOS_ITEM_OC if item.get(k) is not None}
                              for item in items]},
    }


def filas_orden_compra(detalle: dict, filtro) -> list[dict]:
    """Una fila por ítem de la OC QUE PERTENEZCA A UN RUBRO, con su precio unitario.

    Una OC de "insumos clínicos" puede traer guantes (se guardan) y un monitor o
    una sonda (no se guardan); una de consultoría, catering o pasajes."""
    comprador = detalle.get("Comprador") or {}
    proveedor = detalle.get("Proveedor") or {}
    fechas = detalle.get("Fechas") or {}
    base = {
        "codigo_oc": detalle.get("Codigo"),
        "nombre_oc": detalle.get("Nombre"),
        "codigo_licitacion": _texto(detalle.get("CodigoLicitacion")),
        "estado": detalle.get("Estado"),
        "fecha_creacion": _iso(_fecha(fechas.get("FechaCreacion"))),
        "organismo": comprador.get("NombreOrganismo"),
        "region": _texto(comprador.get("RegionUnidad")),
        "proveedor": _texto(proveedor.get("Nombre")),
        "rut_proveedor": proveedor.get("RutSucursal"),
        "moneda": _texto(detalle.get("TipoMoneda")),
    }
    items = (detalle.get("Items") or {}).get("Listado") or []
    filas = []
    for item, resultado in clasificar_items_oc(detalle.get("Nombre"), items, filtro):
        # Un ítem es un solo producto: sus textos se revisan juntos ("Guante nitrilo" +
        # "libre de polvo, látex").
        alertas = filtro.alertas(" ".join(textos_alerta_item_oc(item)))
        cantidad = _numero(item.get("Cantidad"))
        precio = _numero(item.get("PrecioNeto"))
        total = _numero(item.get("Total"))
        # En la API real "Total" del ítem suele venir en 0: se recalcula.
        if not total and cantidad and precio:
            total = cantidad * precio
        filas.append(
            base
            | {
                "rubro": resultado.rubro,
                "rubro_nombre": resultado.rubro_nombre,
                "palabras_detectadas": ", ".join(resultado.palabras),
                "alertas_regulatorias": " | ".join(alertas) if alertas else None,
                "correlativo": item.get("Correlativo"),
                "producto": _texto(item.get("Producto")),
                "categoria": item.get("Categoria"),
                "especificacion_comprador": item.get("EspecificacionComprador"),
                "especificacion_proveedor": item.get("EspecificacionProveedor"),
                "unidad": _texto(item.get("Unidad")),
                "cantidad": cantidad,
                "precio_unitario_neto": precio,
                "total_item": total,
            }
        )
    return filas
