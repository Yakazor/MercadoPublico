"""Descarga de licitaciones activas y su detalle por código."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date

from .almacenamiento import BaseDatos
from .cliente_api import ClienteMercadoPublico, ErrorApi
from .filtro import FiltroRubros
from .modelos import compactar_licitacion, fila_licitacion, productos_licitacion, textos_licitacion

log = logging.getLogger(__name__)


@dataclass
class ResultadoRadar:
    filas: list[dict] = field(default_factory=list)
    fallidas: set[str] = field(default_factory=set)   # detalle no disponible (error de API o sin tiempo)
    candidatas: int = 0
    descargadas: int = 0                              # detalles pedidos a la API
    reutilizadas: int = 0                             # detalles guardados que se reutilizaron
    activas: set[str] = field(default_factory=set)    # códigos del listado de activas


def listar_activas(cliente: ClienteMercadoPublico) -> list[dict]:
    """Listado liviano de todas las licitaciones activas (código, nombre, cierre)."""
    return cliente.licitaciones(estado="activas").get("Listado") or []


def detalle(cliente: ClienteMercadoPublico, codigo: str) -> dict | None:
    listado = cliente.licitaciones(codigo=codigo).get("Listado") or []
    return listado[0] if listado else None


def clasificar(detalle_licitacion: dict, filtro: FiltroRubros, hoy: date | None = None) -> dict | None:
    """Fila lista para guardar si la licitación pertenece a un rubro; si no, None."""
    descripcion, items, items_onu = textos_licitacion(detalle_licitacion)
    productos = productos_licitacion(detalle_licitacion)
    nombre = detalle_licitacion.get("Nombre")
    resultado = filtro.evaluar(*descripcion, nombre=nombre, items=items, items_onu=items_onu, productos=productos)
    if not resultado.coincide:
        return None
    return fila_licitacion(
        detalle_licitacion,
        resultado,
        hoy,
        # Cada línea como un solo texto: el "nitrilo" del producto ONU niega el
        # "libre de polvo, látex" de su descripción.
        alertas=filtro.alertas(nombre, *descripcion, *productos),
        solo_regulados=resultado.solo_regulados,
    )


def radar_licitaciones(
    cliente: ClienteMercadoPublico,
    filtro: FiltroRubros,
    preliminar_por_nombre: bool = True,
    limite: int | None = None,
    hoy: date | None = None,
    db: BaseDatos | None = None,
    refrescar_dias: int = 7,
    hasta_monotonic: float | None = None,
) -> ResultadoRadar:
    """Licitaciones activas que calzan con algún rubro, y las que no se pudieron revisar.

    Con `db`, el detalle de una licitación ya conocida se reutiliza mientras no
    cambie su fecha de cierre en el listado ni pasen `refrescar_dias`. Si se acaba
    el tiempo (`hasta_monotonic`), las que faltan quedan como no revisadas."""
    hoy = hoy or date.today()
    activas = listar_activas(cliente)
    log.info("Licitaciones activas: %d", len(activas))

    if preliminar_por_nombre:
        candidatas = [l for l in activas if filtro.es_candidata(l.get("Nombre"))]
        log.info("Candidatas tras filtro por nombre: %d", len(candidatas))
    else:
        candidatas = activas
    if limite:
        candidatas = candidatas[:limite]

    resultado = ResultadoRadar(candidatas=len(candidatas),
                               activas={l.get("CodigoExterno") for l in activas})
    for i, resumen in enumerate(candidatas, 1):
        codigo = resumen.get("CodigoExterno")
        cierre = resumen.get("FechaCierre")
        guardado = db.detalle_licitacion(codigo) if db is not None else None
        if guardado and guardado[1] == cierre and (hoy - guardado[2]).days < refrescar_dias:
            det = guardado[0]
            resultado.reutilizadas += 1
        else:
            if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
                # Sin tiempo: se conserva lo que haya en la base (como un error de la API).
                resultado.fallidas.add(codigo)
                continue
            try:
                det = detalle(cliente, codigo)
            except ErrorApi as e:
                if e.fatal:
                    raise
                log.error("Sin detalle para %s: %s", codigo, e)
                resultado.fallidas.add(codigo)
                continue
            if not det:
                log.warning("Detalle vacío para %s", codigo)
                resultado.fallidas.add(codigo)
                continue
            resultado.descargadas += 1
            if db is not None:
                db.guardar_detalle_licitacion(codigo, cierre, compactar_licitacion(det), hoy)
        fila = clasificar(det, filtro, hoy)
        if fila:
            resultado.filas.append(fila)
        if i % 25 == 0:
            log.info("Detalle %d/%d", i, len(candidatas))
    log.info("Licitaciones en rubros: %d (detalles descargados: %d, reutilizados: %d, no revisadas: %d)",
             len(resultado.filas), resultado.descargadas, resultado.reutilizadas, len(resultado.fallidas))
    return resultado
