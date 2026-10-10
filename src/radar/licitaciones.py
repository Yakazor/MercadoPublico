"""Descarga de licitaciones activas y su detalle por código."""
from __future__ import annotations

import logging
from datetime import date

from .cliente_api import ClienteMercadoPublico, ErrorApi
from .filtro import FiltroRubros
from .modelos import fila_licitacion, texto_licitacion

log = logging.getLogger(__name__)


def listar_activas(cliente: ClienteMercadoPublico) -> list[dict]:
    """Listado liviano de todas las licitaciones activas (código, nombre, cierre)."""
    return cliente.licitaciones(estado="activas").get("Listado") or []


def detalle(cliente: ClienteMercadoPublico, codigo: str) -> dict | None:
    listado = cliente.licitaciones(codigo=codigo).get("Listado") or []
    return listado[0] if listado else None


def radar_licitaciones(
    cliente: ClienteMercadoPublico,
    filtro: FiltroRubros,
    preliminar_por_nombre: bool = True,
    limite: int | None = None,
    hoy: date | None = None,
) -> list[dict]:
    """Devuelve filas de las licitaciones activas que calzan con algún rubro."""
    activas = listar_activas(cliente)
    log.info("Licitaciones activas: %d", len(activas))

    if preliminar_por_nombre:
        candidatas = [l for l in activas if filtro.evaluar(nombre=l.get("Nombre")).coincide]
        log.info("Candidatas tras filtro por nombre: %d", len(candidatas))
    else:
        candidatas = activas
    if limite:
        candidatas = candidatas[:limite]

    filas = []
    for i, resumen in enumerate(candidatas, 1):
        codigo = resumen.get("CodigoExterno")
        try:
            det = detalle(cliente, codigo)
        except ErrorApi as e:
            log.error("Sin detalle para %s: %s", codigo, e)
            continue
        if not det:
            continue
        resultado = filtro.evaluar(*texto_licitacion(det), nombre=det.get("Nombre"))
        if resultado.coincide:
            filas.append(fila_licitacion(det, resultado, hoy))
        if i % 25 == 0:
            log.info("Detalle %d/%d", i, len(candidatas))
    log.info("Licitaciones en rubros: %d", len(filas))
    return filas
