"""Órdenes de compra históricas para estimar precios adjudicados por rubro."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .almacenamiento import BaseDatos
from .cliente_api import ClienteMercadoPublico, ErrorApi
from .filtro import FiltroRubros, normalizar
from .modelos import filas_orden_compra

log = logging.getLogger(__name__)


def dias(desde: date, hasta: date):
    actual = desde
    while actual <= hasta:
        yield actual
        actual += timedelta(days=1)


@dataclass
class ResultadoDia:
    items: int = 0
    ordenes: int = 0
    fallidas: int = 0       # OC cuyo detalle no se pudo descargar
    candidatas: int = 0

    @property
    def completo(self) -> bool:
        return self.fallidas == 0


def procesar_dia(
    cliente: ClienteMercadoPublico,
    filtro: FiltroRubros,
    db: BaseDatos,
    fecha: date,
    estado: str = "todos",
) -> ResultadoDia:
    """Descarga las OC de un día y guarda los ítems que pertenecen a un rubro.

    Un error en el listado del día se propaga (ErrorApi). Los errores en el
    detalle de una OC se cuentan en `fallidas`: el día no debe marcarse como
    procesado para que la próxima ejecución lo reintente."""
    listado = cliente.ordenes_de_compra(fecha=fecha.strftime("%d%m%Y"), estado=estado).get("Listado") or []
    candidatas = [oc for oc in listado if filtro.es_candidata(oc.get("Nombre"))]
    log.info("%s: %d OC, %d candidatas por nombre", fecha, len(listado), len(candidatas))

    resultado = ResultadoDia(candidatas=len(candidatas))
    for resumen in candidatas:
        codigo = resumen.get("Codigo")
        try:
            det = (cliente.ordenes_de_compra(codigo=codigo).get("Listado") or [None])[0]
        except ErrorApi as e:
            log.error("Sin detalle para OC %s: %s", codigo, e)
            resultado.fallidas += 1
            continue
        if not det:
            log.warning("Detalle vacío para OC %s", codigo)
            continue
        filas = filas_orden_compra(det, filtro)
        # Reemplaza siempre: si la OC ya no tiene ítems del rubro, se borran.
        db.reemplazar_items_oc(codigo, filas)
        if filas:
            resultado.items += len(filas)
            resultado.ordenes += 1
    return resultado


def reclasificar_items(db: BaseDatos, filtro: FiltroRubros) -> tuple[int, int]:
    """Re-evalúa los ítems guardados con el filtro actual, sin llamar a la API.

    Borra los que ya no pertenecen a un rubro y actualiza rubro/palabras/alertas
    del resto (útil tras cambiar config.yaml). Devuelve (actualizados, eliminados)."""
    filas = db.con.execute(
        "SELECT rowid, producto, especificacion_comprador, especificacion_proveedor, categoria "
        "FROM ordenes_compra_items"
    ).fetchall()
    actualizados = eliminados = 0
    with db.con:
        for rowid, *textos in filas:
            textos = [t for t in textos if t]
            resultado = filtro.evaluar_item(*textos)
            if not resultado.coincide:
                db.con.execute("DELETE FROM ordenes_compra_items WHERE rowid = ?", [rowid])
                eliminados += 1
                continue
            alertas = filtro.alertas(*textos)
            db.con.execute(
                "UPDATE ordenes_compra_items SET rubro = ?, rubro_nombre = ?, palabras_detectadas = ?, "
                "alertas_regulatorias = ? WHERE rowid = ?",
                [resultado.rubro, resultado.rubro_nombre, ", ".join(resultado.palabras),
                 " | ".join(alertas) if alertas else None, rowid],
            )
            actualizados += 1
    return actualizados, eliminados


COLUMNAS_RESUMEN = [
    "rubro_nombre", "producto_normalizado", "unidad", "moneda",
    "n_items", "n_ordenes", "n_proveedores", "cantidad_total",
    "precio_min", "precio_p25", "precio_mediana", "precio_p75", "precio_max",
    "monto_total", "alertas_regulatorias",
]


def resumen_precios(items: pd.DataFrame) -> pd.DataFrame:
    """Estadísticas de precio unitario neto por rubro, producto y unidad."""
    if items.empty:
        return pd.DataFrame(columns=COLUMNAS_RESUMEN)
    df = items.dropna(subset=["precio_unitario_neto"]).copy()
    df = df[df["precio_unitario_neto"] > 0]
    # Las OC canceladas no reflejan un precio realmente pagado.
    cancelada = df["estado"].fillna("").map(normalizar).str.contains("cancelad")
    df = df[~cancelada]
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
    })
    if "alertas_regulatorias" in df.columns:
        resumen["alertas_regulatorias"] = agrupado["alertas_regulatorias"].agg(_unir_alertas)
    else:
        resumen["alertas_regulatorias"] = None
    resumen = resumen.reset_index().reindex(columns=COLUMNAS_RESUMEN)
    return resumen.sort_values(["rubro_nombre", "monto_total"], ascending=[True, False])


def _unir_alertas(serie: pd.Series) -> str | None:
    notas = sorted({n for valor in serie.dropna() for n in str(valor).split(" | ") if n})
    return " | ".join(notas) or None
