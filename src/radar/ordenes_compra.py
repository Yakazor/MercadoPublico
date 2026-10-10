"""Órdenes de compra históricas para estimar precios adjudicados por rubro."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from .almacenamiento import BaseDatos
from .cliente_api import ClienteMercadoPublico, ErrorApi
from .filtro import FiltroRubros, normalizar
from .modelos import filas_orden_compra, texto_orden_compra

log = logging.getLogger(__name__)


def dias(desde: date, hasta: date):
    actual = desde
    while actual <= hasta:
        yield actual
        actual += timedelta(days=1)


def procesar_dia(
    cliente: ClienteMercadoPublico,
    filtro: FiltroRubros,
    db: BaseDatos,
    fecha: date,
    estado: str = "todos",
) -> int:
    """Descarga las OC de un día, filtra por rubro y guarda sus ítems."""
    listado = cliente.ordenes_de_compra(fecha=fecha.strftime("%d%m%Y"), estado=estado).get("Listado") or []
    candidatas = [oc for oc in listado if filtro.evaluar(nombre=oc.get("Nombre")).coincide]
    log.info("%s: %d OC, %d candidatas por nombre", fecha, len(listado), len(candidatas))

    guardadas = 0
    for resumen in candidatas:
        codigo = resumen.get("Codigo")
        try:
            det = (cliente.ordenes_de_compra(codigo=codigo).get("Listado") or [None])[0]
        except ErrorApi as e:
            log.error("Sin detalle para OC %s: %s", codigo, e)
            continue
        if not det:
            continue
        resultado = filtro.evaluar(*texto_orden_compra(det), nombre=det.get("Nombre"))
        if resultado.coincide:
            guardadas += db.guardar_items_oc(filas_orden_compra(det, resultado))
    return guardadas


def resumen_precios(items: pd.DataFrame) -> pd.DataFrame:
    """Estadísticas de precio unitario neto por rubro, producto y unidad."""
    if items.empty:
        return items
    df = items.dropna(subset=["precio_unitario_neto"]).copy()
    df = df[df["precio_unitario_neto"] > 0]
    df["producto_normalizado"] = df["producto"].map(normalizar)
    agrupado = df.groupby(["rubro_nombre", "producto_normalizado", "unidad", "moneda"], dropna=False)
    precio = agrupado["precio_unitario_neto"]
    resumen = pd.DataFrame({
        "n_items": agrupado.size(),
        "n_ordenes": agrupado["codigo_oc"].nunique(),
        "n_proveedores": agrupado["proveedor"].nunique(),
        "cantidad_total": agrupado["cantidad"].sum(),
        "precio_min": precio.min(),
        "precio_p25": precio.quantile(0.25),
        "precio_mediana": precio.median(),
        "precio_p75": precio.quantile(0.75),
        "precio_max": precio.max(),
        "monto_total": agrupado["total_item"].sum(),
    }).reset_index()
    return resumen.sort_values(["rubro_nombre", "monto_total"], ascending=[True, False])
