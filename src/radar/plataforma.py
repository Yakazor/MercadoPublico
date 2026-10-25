"""Datos y cálculos de la plataforma web (`plataforma/app.py`).

La plataforma lee los JSON que el radar publica en la rama `datos` (los mismos del
dashboard) y usa el código del radar para todo lo demás: presupuesto
(`armar_presupuesto`), evaluación GO / NO GO (`evaluar`) y orden de compra al proveedor
(`crear_orden`). Aquí queda lo que no depende de Streamlit, para poder probarlo.

- `leer_datos(origen)`: licitaciones, ítems, precios de mercado y meta, desde la URL de
  la rama `datos` o desde una carpeta local.
- `preparar(datos, ahora)`: solo las abiertas, con los días al cierre recalculados (los
  JSON se generan una vez al día) e ítems y precios agrupados por código.
- `opciones(...)`: precios de tiendas + tus cotizaciones (mandan sobre las tiendas) y,
  si se pide, una estimación con lo que pagó el Estado para las líneas sin precio.
- `evaluar_licitacion(...)` y `ranking(...)`: presupuesto y evaluación con tus supuestos.
- `datos_orden(...)` y `orden_xlsx(...)`: orden de compra al proveedor desde el presupuesto.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .config import cargar_config
from .evaluacion import SUPUESTOS, evaluar, puntaje
from .filtro import normalizar
from .orden_proveedor import crear_orden
from .presupuesto import armar_presupuesto

ORIGEN_DATOS = "https://raw.githubusercontent.com/Yakazor/MercadoPublico/datos"
ARCHIVOS = ("licitaciones", "items", "mercado", "meta")
CHILE = ZoneInfo("America/Santiago")
COMPRA_AGIL = "Compra Ágil"
COTIZACION = "Cotización ingresada"
ESTIMADA_OC = "estimada (OC)"


def leer_datos(origen: str = ORIGEN_DATOS, timeout: float = 60) -> dict:
    """Los JSON de la rama `datos`, desde su URL (raw de GitHub) o desde una carpeta."""
    datos = {}
    for nombre in ARCHIVOS:
        if origen.startswith(("http://", "https://")):
            r = requests.get(f"{origen.rstrip('/')}/{nombre}.json", timeout=timeout)
            r.raise_for_status()
            datos[nombre] = r.json()
        else:
            datos[nombre] = json.loads((Path(origen) / f"{nombre}.json").read_text(encoding="utf-8"))
    return datos


def cierre(lic: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(lic["fecha_cierre"]).replace(tzinfo=CHILE)
    except (KeyError, TypeError, ValueError):
        return None


def preparar(datos: dict, ahora: datetime | None = None) -> dict:
    """Licitaciones y Compras Ágiles abiertas (cierre después de `ahora`, hora de Chile)."""
    ahora = ahora or datetime.now(CHILE)
    abiertas = []
    for lic in datos["licitaciones"]:
        c = cierre(lic)
        if c is not None and c <= ahora:
            continue
        abiertas.append(lic | {"dias_restantes": (c.date() - ahora.date()).days if c else None})
    items, mercado = {}, {}
    for it in datos.get("items") or []:
        items.setdefault(it["codigo"], []).append(it)
    for op in datos.get("mercado") or []:
        if not op.get("descartado"):
            mercado.setdefault(op["codigo"], []).append(op)
    meta = datos.get("meta") or {}
    meta = (meta[0] if meta else {}) if isinstance(meta, list) else meta
    return {"licitaciones": abiertas, "items": items, "mercado": mercado, "meta": meta}


def es_compra_agil(lic: dict) -> bool:
    return lic.get("tipo") == COMPRA_AGIL


def filtrar(lics: list[dict], *, texto: str = "", compra_agil: bool | None = None, rubros=(), regiones=(),
            max_dias: int | None = None, monto_min: float | None = None, monto_max: float | None = None,
            con_precios: set | None = None, plazo_max: float | None = None, llamado: int | None = None) -> list[dict]:
    """Filtros de la tabla. Los de monto y plazo no descartan las que no informan ese dato."""
    palabras = normalizar(texto).split()
    salida = []
    for lic in lics:
        if compra_agil is not None and es_compra_agil(lic) != compra_agil:
            continue
        if palabras:
            buscable = normalizar(" ".join(str(lic.get(k) or "") for k in
                                           ("codigo", "nombre", "organismo", "palabras_detectadas", "comuna")))
            if not all(p in buscable for p in palabras):
                continue
        if rubros and lic.get("rubro_nombre") not in rubros:
            continue
        if regiones and lic.get("region") not in regiones:
            continue
        dias = lic.get("dias_restantes")
        if max_dias is not None and dias is not None and dias > max_dias:
            continue
        monto = lic.get("monto_estimado")
        if monto is not None and ((monto_min and monto < monto_min) or (monto_max and monto > monto_max)):
            continue
        if con_precios is not None and lic["codigo"] not in con_precios:
            continue
        plazo = lic.get("plazo_entrega_dias")
        if plazo_max is not None and plazo is not None and plazo > plazo_max:
            continue
        if llamado is not None and lic.get("llamado") != llamado:
            continue
        salida.append(lic)
    return sorted(salida, key=lambda l: l.get("fecha_cierre") or "9999")


def opciones(items: list[dict], mercado: list[dict], cotizaciones: dict | None = None, estimar_oc: bool = False,
             margen: float = 0.20, otros: float = 0.05) -> list[dict]:
    """Opciones de precio para `armar_presupuesto`.

    - `cotizaciones`: {línea: precio unitario neto} que te dio un proveedor; reemplazan a
      las tiendas de esa línea y cuentan como producto exacto y verificado;
    - `estimar_oc`: para las líneas sin precio, el costo máximo que permite ofertar la
      mediana que pagó el Estado (la oferta queda igual a esa mediana). Cuenta como
      producto aproximado y sin verificar: suma riesgo y una condición en la evaluación.
    """
    cotizaciones = {linea: precio for linea, precio in (cotizaciones or {}).items() if precio and precio > 0}
    filas = [op for op in mercado if op.get("linea") not in cotizaciones]
    filas += [{"linea": linea, "precio_unitario_neto": precio, "coincidencia": "exacta", "verificado": True,
               "tienda": COTIZACION} for linea, precio in cotizaciones.items()]
    if estimar_oc:
        con_precio = {f.get("linea") for f in filas if (f.get("precio_unitario_neto") or 0) > 0}
        for it in items:
            if it.get("linea") not in con_precio and it.get("ref_mediana"):
                filas.append({"linea": it["linea"], "precio_unitario_neto": it["ref_mediana"] / ((1 + otros) * (1 + margen)),
                              "coincidencia": ESTIMADA_OC, "verificado": False, "tienda": "Estimado con OC del Estado"})
    return filas


def evaluar_licitacion(lic: dict, items: list[dict], ops: list[dict], supuestos: dict | None = None,
                       margen: float = 0.20, otros: float = 0.05) -> tuple[dict, object]:
    p = armar_presupuesto(items, ops, margen=margen, otros_costos=otros)
    return p, evaluar(lic, p, supuestos)


def ranking(prep: dict, supuestos: dict | None = None, margen: float = 0.20, otros: float = 0.05,
            estimar_oc: bool = False, cotizaciones: dict | None = None) -> list[tuple]:
    """(licitación, presupuesto, evaluación) de las que tienen al menos un precio, de mejor a peor."""
    cotizaciones = cotizaciones or {}
    filas = []
    for lic in prep["licitaciones"]:
        codigo = lic["codigo"]
        items = prep["items"].get(codigo)
        mercado = prep["mercado"].get(codigo, [])
        if not items or not (mercado or estimar_oc or cotizaciones.get(codigo)):
            continue
        ops = opciones(items, mercado, cotizaciones.get(codigo), estimar_oc, margen, otros)
        p, ev = evaluar_licitacion(lic, items, ops, supuestos, margen, otros)
        if p["items_sin_precio"] < len(p["items"]):
            filas.append((lic, p, ev))
    return sorted(filas, key=lambda t: -puntaje(t[2]))


def supuestos_config(config: dict | None = None) -> dict:
    """Supuestos de la evaluación con lo que diga `config.yaml > evaluacion`."""
    conf = (config if config is not None else cargar_config()).get("evaluacion") or {}
    return SUPUESTOS | {k: v for k, v in conf.items() if k in SUPUESTOS}


def mercado_por_item(ops: list[dict]) -> dict:
    """Las opciones planas de la rama `datos` en el formato de `informes/mercado/<codigo>.json`."""
    items = {}
    for op in ops:
        items.setdefault(op.get("linea"), []).append(op)
    return {"items": [{"linea": linea, "opciones": lista} for linea, lista in items.items()]}


def datos_orden(lic: dict, p: dict, tienda: str | None = None) -> dict:
    """Datos para `crear_orden` desde el presupuesto: los ítems (de una tienda, o todos) con su
    cantidad y costo unitario neto; el lugar de entrega de la Compra Ágil si lo informa."""
    items = []
    for it in p["items"]:
        if tienda and it.get("tienda") != tienda:
            continue
        descripcion = it.get("producto_mercado") or (
            it.get("descripcion") if es_compra_agil(lic) and it.get("descripcion") else it.get("producto"))
        costo = it.get("costo_unitario_neto")
        items.append({"descripcion": " ".join(str(descripcion or "").split())[:200], "unidad": it.get("unidad"),
                      "cantidad": it.get("cantidad"), "precio_unitario_neto": round(costo) if costo else None})
    condiciones = {}
    if lic.get("direccion_entrega"):
        condiciones["lugar_entrega"] = f"{lic['direccion_entrega']} ({lic.get('organismo') or ''})".replace(" ()", "")
    return {"referencia": {"licitacion": lic["codigo"], "oc_estado": ""}, "items": items, "condiciones": condiciones}


def orden_xlsx(datos: dict) -> bytes:
    archivo = io.BytesIO()
    crear_orden(datos).save(archivo)
    return archivo.getvalue()
