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


def texto_licitacion(detalle: dict) -> list[str]:
    """Textos (además del nombre) sobre los que se aplica el filtro de rubros."""
    textos = [detalle.get("Descripcion")]
    for item in items_licitacion(detalle):
        textos += [item.get("NombreProducto"), item.get("Descripcion"), item.get("Categoria")]
    return [t for t in textos if t]


def fila_licitacion(detalle: dict, resultado_filtro, hoy: date | None = None) -> dict:
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
        "url": f"https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion={detalle.get('CodigoExterno')}",
    }


def filas_orden_compra(detalle: dict, resultado_filtro) -> list[dict]:
    """Una fila por ítem de la OC, con precio unitario para análisis de márgenes."""
    comprador = detalle.get("Comprador") or {}
    proveedor = detalle.get("Proveedor") or {}
    fechas = detalle.get("Fechas") or {}
    base = {
        "codigo_oc": detalle.get("Codigo"),
        "nombre_oc": detalle.get("Nombre"),
        "codigo_licitacion": detalle.get("CodigoLicitacion"),
        "estado": detalle.get("Estado"),
        "fecha_creacion": _iso(_fecha(fechas.get("FechaCreacion"))),
        "organismo": comprador.get("NombreOrganismo"),
        "region": _texto(comprador.get("RegionUnidad")),
        "proveedor": _texto(proveedor.get("Nombre")),
        "rut_proveedor": proveedor.get("RutSucursal"),
        "moneda": detalle.get("TipoMoneda"),
        "rubro": resultado_filtro.rubro,
        "rubro_nombre": resultado_filtro.rubro_nombre,
        "palabras_detectadas": ", ".join(resultado_filtro.palabras),
    }
    filas = []
    for item in (detalle.get("Items") or {}).get("Listado") or []:
        cantidad = _numero(item.get("Cantidad"))
        precio = _numero(item.get("PrecioNeto"))
        total = _numero(item.get("Total"))
        # En la API real "Total" del ítem suele venir en 0: se recalcula.
        if not total and cantidad and precio:
            total = cantidad * precio
        filas.append(
            base
            | {
                "correlativo": item.get("Correlativo"),
                "producto": item.get("Producto"),
                "categoria": item.get("Categoria"),
                "especificacion_comprador": item.get("EspecificacionComprador"),
                "especificacion_proveedor": item.get("EspecificacionProveedor"),
                "unidad": item.get("Unidad"),
                "cantidad": cantidad,
                "precio_unitario_neto": precio,
                "total_item": total,
            }
        )
    return filas


def texto_orden_compra(detalle: dict) -> list[str]:
    textos = [detalle.get("Descripcion")]
    for item in (detalle.get("Items") or {}).get("Listado") or []:
        textos += [
            item.get("Producto"),
            item.get("Categoria"),
            item.get("EspecificacionComprador"),
            item.get("EspecificacionProveedor"),
        ]
    return [t for t in textos if t]
