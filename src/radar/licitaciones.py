"""Descarga de licitaciones activas y su detalle por código."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from .cliente_api import ClienteMercadoPublico, ErrorApi
from .filtro import FiltroRubros
from .modelos import fila_licitacion, textos_licitacion

log = logging.getLogger(__name__)


@dataclass
class ResultadoRadar:
    filas: list[dict] = field(default_factory=list)
    fallidas: set[str] = field(default_factory=set)   # detalle no disponible (error de API)
    candidatas: int = 0


def listar_activas(cliente: ClienteMercadoPublico) -> list[dict]:
    """Listado liviano de todas las licitaciones activas (código, nombre, cierre)."""
    return cliente.licitaciones(estado="activas").get("Listado") or []


def detalle(cliente: ClienteMercadoPublico, codigo: str) -> dict | None:
    listado = cliente.licitaciones(codigo=codigo).get("Listado") or []
    return listado[0] if listado else None


def clasificar(detalle_licitacion: dict, filtro: FiltroRubros, hoy: date | None = None) -> dict | None:
    """Fila lista para guardar si la licitación pertenece a un rubro; si no, None."""
    descripcion, items, items_onu = textos_licitacion(detalle_licitacion)
    nombre = detalle_licitacion.get("Nombre")
    resultado = filtro.evaluar(*descripcion, nombre=nombre, items=items, items_onu=items_onu)
    if not resultado.coincide:
        return None
    return fila_licitacion(
        detalle_licitacion,
        resultado,
        hoy,
        alertas=filtro.alertas(nombre, *descripcion, *items, *items_onu),
        solo_regulados=resultado.solo_regulados,
    )


def radar_licitaciones(
    cliente: ClienteMercadoPublico,
    filtro: FiltroRubros,
    preliminar_por_nombre: bool = True,
    limite: int | None = None,
    hoy: date | None = None,
) -> ResultadoRadar:
    """Licitaciones activas que calzan con algún rubro, y las que no se pudieron revisar."""
    activas = listar_activas(cliente)
    log.info("Licitaciones activas: %d", len(activas))

    if preliminar_por_nombre:
        candidatas = [l for l in activas if filtro.es_candidata(l.get("Nombre"))]
        log.info("Candidatas tras filtro por nombre: %d", len(candidatas))
    else:
        candidatas = activas
    if limite:
        candidatas = candidatas[:limite]

    resultado = ResultadoRadar(candidatas=len(candidatas))
    for i, resumen in enumerate(candidatas, 1):
        codigo = resumen.get("CodigoExterno")
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
        fila = clasificar(det, filtro, hoy)
        if fila:
            resultado.filas.append(fila)
        if i % 25 == 0:
            log.info("Detalle %d/%d", i, len(candidatas))
    log.info("Licitaciones en rubros: %d (sin detalle por error: %d)", len(resultado.filas), len(resultado.fallidas))
    return resultado
