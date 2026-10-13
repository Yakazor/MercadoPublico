"""Órdenes de compra históricas para estimar precios adjudicados por rubro."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from .almacenamiento import BaseDatos
from .cliente_api import ClienteMercadoPublico, ErrorApi
from .filtro import FiltroRubros, normalizar
from .modelos import clasificar_items_oc, compactar_oc, filas_orden_compra, textos_alerta_item_oc

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
    fallidas: list[str] = field(default_factory=list)   # OC cuyo detalle no se pudo descargar
    candidatas: int = 0
    purgadas: int = 0                                     # OC guardadas que ya no son candidatas
    interrumpido: bool = False                            # se acabó el tiempo a mitad del día

    @property
    def completo(self) -> bool:
        return not self.fallidas and not self.interrumpido


def procesar_dia(
    cliente: ClienteMercadoPublico,
    filtro: FiltroRubros,
    db: BaseDatos,
    fecha: date,
    estado: str = "todos",
    hasta_monotonic: float | None = None,
) -> ResultadoDia:
    """Descarga las OC de un día y guarda los ítems que pertenecen a un rubro.

    Un error en el listado del día se propaga (ErrorApi). Los errores en el
    detalle de una OC quedan en `fallidas` y, si se acaba el tiempo
    (`hasta_monotonic`), `interrumpido`: en ambos casos el día no está completo."""
    listado = cliente.ordenes_de_compra(fecha=fecha.strftime("%d%m%Y"), estado=estado).get("Listado") or []
    db.guardar_listado_oc(fecha, listado)
    candidatas = [oc for oc in listado if filtro.es_candidata(oc.get("Nombre"))]
    log.info("%s: %d OC, %d candidatas por nombre", fecha, len(listado), len(candidatas))

    resultado = ResultadoDia(candidatas=len(candidatas))
    # OC ya guardadas que con la config actual dejaron de ser candidatas: se borran.
    guardadas = db.codigos_oc()
    codigos_candidatas = {oc.get("Codigo") for oc in candidatas}
    for oc in listado:
        codigo = oc.get("Codigo")
        if codigo in guardadas and codigo not in codigos_candidatas:
            db.reemplazar_items_oc(codigo, [])
            resultado.purgadas += 1

    for resumen in candidatas:
        if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
            resultado.interrumpido = True
            log.warning("%s: se acabó el tiempo; el día queda pendiente.", fecha)
            break
        codigo = resumen.get("Codigo")
        try:
            det = (cliente.ordenes_de_compra(codigo=codigo).get("Listado") or [None])[0]
        except ErrorApi as e:
            if e.fatal:
                raise
            if not e.temporal:
                # Definitivo (p. ej. código inválido): reintentar no sirve.
                log.warning("OC %s descartada por error definitivo de la API: %s", codigo, e)
                continue
            log.error("Sin detalle para OC %s: %s", codigo, e)
            resultado.fallidas.append(codigo)
            continue
        if not det:
            log.warning("Detalle vacío para OC %s", codigo)
            continue
        filas = filas_orden_compra(det, filtro)
        # Reemplaza siempre: si la OC ya no tiene ítems del rubro, se borran. El
        # detalle se guarda aunque no tenga ítems del rubro (para reclasificar).
        db.guardar_oc(codigo, fecha, compactar_oc(det), filas)
        if filas:
            resultado.items += len(filas)
            resultado.ordenes += 1
    return resultado


def candidatas_sin_detalle(db: BaseDatos, filtro: FiltroRubros) -> list[tuple[date, str]]:
    """OC de días ya procesados que con la config actual son candidatas por nombre
    pero nunca se descargaron (p. ej. tras agregar "escobas" a palabras_clave)."""
    con_detalle = db.codigos_con_detalle()
    return [(fecha, codigo) for fecha, pares in db.listados_oc() if db.dia_oc_procesado(fecha)
            for codigo, nombre in pares if codigo not in con_detalle and filtro.es_candidata(nombre)]


def completar_candidatas(cliente: ClienteMercadoPublico, filtro: FiltroRubros, db: BaseDatos,
                         hasta_monotonic: float | None = None) -> tuple[int, int]:
    """Descarga solo las OC de `candidatas_sin_detalle`. Devuelve (descargadas,
    pendientes). Las que fallan temporalmente se intentan en la próxima ejecución."""
    faltan = candidatas_sin_detalle(db, filtro)
    descargadas = 0
    for i, (fecha, codigo) in enumerate(faltan):
        if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
            return descargadas, len(faltan) - i
        try:
            det = (cliente.ordenes_de_compra(codigo=codigo).get("Listado") or [None])[0]
        except ErrorApi as e:
            if e.fatal:
                raise
            if e.temporal:
                continue
            det = None  # definitivo: se guarda vacío para no pedirla de nuevo
        db.guardar_oc(codigo, fecha, compactar_oc(det) if det else {"Codigo": codigo},
                      filas_orden_compra(det, filtro) if det else [])
        descargadas += 1
    return descargadas, 0


def reclasificar_items(db: BaseDatos, filtro: FiltroRubros) -> tuple[int, int, int]:
    """Re-evalúa las OC guardadas con el filtro actual, sin llamar a la API.

    Las OC con detalle guardado se reclasifican completas (`filas_orden_compra`):
    se agregan los ítems que ahora pertenecen a un rubro y se borran los que no.
    Las OC antiguas, sin detalle, solo pueden actualizarse o borrarse (misma
    lógica, `clasificar_items_oc`). Devuelve (actualizados, eliminados, agregados)."""
    antes: dict[str, set] = {}
    for codigo, correlativo in db.con.execute("SELECT codigo_oc, correlativo FROM ordenes_compra_items"):
        antes.setdefault(codigo, set()).add(correlativo)

    actualizados = eliminados = agregados = 0
    detalles = db.detalles_oc()
    with db.con:
        for codigo, detalle in detalles:
            filas = filas_orden_compra(detalle, filtro)
            previos, nuevos = antes.get(codigo, set()), {f["correlativo"] for f in filas}
            actualizados += len(previos & nuevos)
            eliminados += len(previos - nuevos)
            agregados += len(nuevos - previos)
            db._reemplazar_items(codigo, filas)

    con_detalle = {codigo for codigo, _ in detalles}
    filas = db.con.execute(
        "SELECT rowid, codigo_oc, nombre_oc, producto, categoria, especificacion_comprador, "
        "especificacion_proveedor FROM ordenes_compra_items"
    ).fetchall()
    por_oc: dict[str, list] = {}
    for fila in filas:
        if fila[1] not in con_detalle:
            por_oc.setdefault(fila[1], []).append(fila)

    with db.con:
        for codigo, filas_oc in por_oc.items():
            nombre_oc = filas_oc[0][2]
            items = [{"rowid": f[0], "Producto": f[3], "Categoria": f[4],
                      "EspecificacionComprador": f[5], "EspecificacionProveedor": f[6]} for f in filas_oc]
            vigentes = {item["rowid"]: r for item, r in clasificar_items_oc(nombre_oc, items, filtro)}
            for item in items:
                r = vigentes.get(item["rowid"])
                if r is None:
                    db.con.execute("DELETE FROM ordenes_compra_items WHERE rowid = ?", [item["rowid"]])
                    eliminados += 1
                    continue
                alertas = filtro.alertas(" ".join(textos_alerta_item_oc(item)))
                db.con.execute(
                    "UPDATE ordenes_compra_items SET rubro = ?, rubro_nombre = ?, palabras_detectadas = ?, "
                    "alertas_regulatorias = ? WHERE rowid = ?",
                    [r.rubro, r.rubro_nombre, ", ".join(r.palabras),
                     " | ".join(alertas) if alertas else None, item["rowid"]],
                )
                actualizados += 1
    return actualizados, eliminados, agregados


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
        # Se marca el producto si la mayoría de sus ítems tiene alerta.
        resumen["alertas_regulatorias"] = agrupado["alertas_regulatorias"].agg(
            lambda s: _unir_alertas(s) if s.notna().mean() >= 0.5 else None)
    else:
        resumen["alertas_regulatorias"] = None
    resumen = resumen.reset_index().reindex(columns=COLUMNAS_RESUMEN)
    return resumen.sort_values(["rubro_nombre", "monto_total"], ascending=[True, False])


def _unir_alertas(serie: pd.Series) -> str | None:
    notas = sorted({n for valor in serie.dropna() for n in str(valor).split(" | ") if n})
    return " | ".join(notas) or None
