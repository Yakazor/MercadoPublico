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


def textos_licitacion(detalle: dict) -> tuple[list[str], list[str]]:
    """(descripción, ítems) para el filtro. El nombre se pasa aparte.

    Los ítems (producto, descripción de la línea, categoría) describen lo que se
    compra; la descripción general suele mencionar además la unidad solicitante."""
    descripcion = [t for t in [detalle.get("Descripcion")] if t]
    items = []
    for item in items_licitacion(detalle):
        items += [item.get("NombreProducto"), item.get("Descripcion"), item.get("Categoria")]
    return descripcion, [t for t in items if t]


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


def clasificar_items_oc(nombre_oc: str | None, items: list[dict], filtro) -> list[tuple[dict, object]]:
    """[(item, Resultado)] de los ítems que pertenecen a un rubro.

    - Si el nombre de la OC está excluido (p. ej. "Guantes de cuero para soldador"
      o "Compra de medicamentos…"), no se guarda nada.
    - Cada ítem se clasifica por su producto/categoría (`filtro.evaluar_item`).
    - Si NINGÚN ítem trae palabra clave (productos genéricos o marcas) pero el
      nombre de la OC sí, se usan todos los ítems no excluidos con el rubro del
      nombre ("Compra de guantes de nitrilo" con ítem "NITRIDERM M CAJA 100")."""
    if nombre_oc and not filtro.es_candidata(nombre_oc):
        return []
    evaluados = [
        (item, filtro.evaluar_item(item.get("Producto") or item.get("EspecificacionComprador"),
                                   item.get("Categoria")))
        for item in items
    ]
    if not any(r.coincide for _, r in evaluados) and nombre_oc:
        por_nombre = filtro.evaluar(nombre=nombre_oc)
        if por_nombre.coincide:
            evaluados = [(item, r if r.excluido else por_nombre) for item, r in evaluados]
    return [(item, r) for item, r in evaluados if r.coincide]


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
        alertas = filtro.alertas(*textos_item_oc(item))
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
