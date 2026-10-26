"""Datos y cálculos de la plataforma web (`plataforma/app.py`).

La plataforma lee los JSON que el radar publica en la rama `datos` (los mismos del
dashboard) y usa el código del radar para todo lo demás: presupuesto
(`armar_presupuesto`), evaluación GO / NO GO (`evaluar`) y orden de compra al proveedor
(`crear_orden`). Aquí queda lo que no depende de Streamlit, para poder probarlo.

- `leer_datos(origen)`: licitaciones, ítems, precios de mercado y meta, desde la URL de
  la rama `datos` o desde una carpeta local.
- `version_datos(origen)` y `origen_en_commit(origen, sha)`: el último commit publicado en la
  rama `datos` y la URL de ese commit, para que la plataforma note cada publicación al tiro.
- `preparar(datos, ahora)`: solo las abiertas, con los días al cierre recalculados (los
  JSON se generan una vez al día) e ítems y precios agrupados por código.
- `opciones(...)`: precios de tiendas + tus cotizaciones (mandan sobre las tiendas) y,
  si se pide, una estimación con lo que pagó el Estado para las líneas sin precio.
- `evaluar_licitacion(...)` y `ranking(...)`: presupuesto y evaluación con tus supuestos.
- `datos_orden(...)` y `orden_xlsx(...)`: orden de compra al proveedor desde el presupuesto.
- `compra_venta(lic, items)`: si se puede ofertar comprando los productos hechos y revendiéndolos.
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .config import cargar_config
from .evaluacion import SUPUESTOS, evaluar, puntaje
from .filtro import normalizar
from .orden_proveedor import crear_orden
from .presupuesto import armar_presupuesto, unidad_global

ORIGEN_DATOS = "https://raw.githubusercontent.com/Yakazor/MercadoPublico/datos"
ARCHIVOS = ("licitaciones", "items", "mercado", "meta")
CHILE = ZoneInfo("America/Santiago")
COMPRA_AGIL = "Compra Ágil"
COTIZACION = "Cotización ingresada"
ESTIMADA_OC = "estimada (OC)"

# Ítems que se pueden cotizar (también los usa scripts/seleccionar_mercado.py): con unidad
# física, la misma regla que el presupuesto (`unidad_global`).
_SEGUN = re.compile(r"seg[uú]n (bases|detalle|cantidades|anexo|especificaciones|lo indicado)|de acuerdo a (las )?bases", re.I)
# Descripciones que nombran una categoría y no un producto ("Mobiliario para la oficina X").
_GENERICA = re.compile(r"^(mobiliario|insumos|materiales|equipamiento|articulos|art[ií]culos|equipos|productos)\b", re.I)
# Licencias y soporte de software: exigen ser partner del fabricante, no se compran y revenden («soporte»
# solo es un producto: soporte de monitor, de pared).
_SOFTWARE = re.compile(r"licenci|software|suscripci|soporte (t[eé]cnico|inform[aá]tico|de software)", re.I)
# Lo que no se compra hecho para revender (sobre el texto normalizado, sin tildes). «Servicio» solo no
# basta: «Servicio de Salud» o «Servicio de Urgencia» son nombres de organismos.
_SERVICIO_DESCRIPCION = re.compile(
    r"\b(instalacion|instalar|mantencion|mantenimiento|reparacion|capacitacion|curso|arriendo|arrendamiento|"
    r"confeccion|confeccionar|bordados?|estampados?|serigrafia|consultoria|asesoria|catering|fabricacion|"
    r"a medida|mano de obra|servicios? de (instalacion|mantencion|mantenimiento|reparacion|traslado|transporte|"
    r"aseo|limpieza|alimentacion|impresion))\b")
# Productos ONU que son servicios ("Servicios de consultoría…", "Mantenimiento de…", "Capacitación…").
_SERVICIO_PRODUCTO = re.compile(r"^(servicios?|mantenimiento|mantencion|reparacion|capacitacion|formacion|arriendo|"
                                r"alquiler|instalacion|consultoria|asesoria)\b")


def leer_datos(origen: str = ORIGEN_DATOS, timeout: float = 60, marca: str | None = None) -> dict:
    """Los JSON de la rama `datos`, desde su URL (raw de GitHub) o desde una carpeta.

    `marca` va como parámetro de la URL: GitHub guarda en caché los archivos unos minutos y
    una marca nueva obliga a traer la versión recién publicada."""
    datos = {}
    for nombre in ARCHIVOS:
        if origen.startswith(("http://", "https://")):
            r = requests.get(f"{origen.rstrip('/')}/{nombre}.json", params={"v": marca} if marca else None,
                             timeout=timeout)
            r.raise_for_status()
            datos[nombre] = r.json()
        else:
            datos[nombre] = json.loads((Path(origen) / f"{nombre}.json").read_text(encoding="utf-8"))
    return datos


_RAW_GITHUB = re.compile(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/?$")


def version_datos(origen: str = ORIGEN_DATOS, timeout: float = 10) -> str | None:
    """Commit de la rama de `origen` (URL raw de GitHub), como `git ls-remote`, que GitHub no
    guarda en caché ni limita por hora. None si el origen es otro o GitHub no responde."""
    m = _RAW_GITHUB.match(origen)
    if not m:
        return None
    dueno, repo, rama = m.groups()
    try:
        r = requests.get(f"https://github.com/{dueno}/{repo}.git/info/refs", params={"service": "git-upload-pack"},
                         timeout=timeout)
        r.raise_for_status()
    except requests.RequestException:
        return None
    encontrado = re.search(rf"([0-9a-f]{{40}}) refs/heads/{re.escape(rama)}(?:\x00|\n|$)", r.text)
    return encontrado.group(1) if encontrado else None


def origen_en_commit(origen: str, sha: str | None) -> str:
    """La URL raw de `origen` fijada en el commit `sha`: sus archivos no cambian, así que la caché
    de GitHub nunca entrega una versión vieja. Sin `sha` (u otro origen), queda igual."""
    m = _RAW_GITHUB.match(origen)
    if not m or not sha:
        return origen
    dueno, repo, _ = m.groups()
    return f"https://raw.githubusercontent.com/{dueno}/{repo}/{sha}"


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


def dias_al_cierre(lic: dict, hoy) -> int | None:
    """Días desde `hoy` (fecha de Chile) hasta el cierre. El `dias_restantes` publicado se calculó
    cuando corrió el radar o Compra Ágil (puede tener horas): se usa solo si la fecha no se lee."""
    try:
        return (datetime.fromisoformat(str(lic.get("fecha_cierre") or "")[:10]).date() - hoy).days
    except ValueError:
        return lic.get("dias_restantes")


def item_concreto(item: dict) -> bool:
    """Ítem que se puede cotizar: cantidad, unidad física y una descripción propia."""
    descripcion = (item.get("descripcion") or "").strip()
    return (bool(item.get("cantidad")) and not unidad_global(item.get("unidad")) and len(descripcion) >= 8
            and not _SEGUN.search(descripcion) and not _GENERICA.search(descripcion)
            and not _SOFTWARE.search(f"{item.get('producto') or ''} {descripcion}"))


def compra_venta(lic: dict, items: list[dict]) -> tuple[bool | None, str]:
    """¿Se puede ofertar comprando los productos hechos y revendiéndolos? (sí / no / None = revisar las
    bases, y por qué).

    No: exige registro ISP, es consultoría o algún ítem es un servicio (instalación, mantención,
    confección, bordado, arriendo, capacitación, licencias…). Revisar: el radar no trae los ítems o
    alguno no dice qué ni cuánto («1 Global», «según bases», una categoría en vez de un producto).
    """
    if lic.get("alertas_regulatorias"):
        return False, f"Requiere registro ISP ({lic['alertas_regulatorias']})"
    if lic.get("rubro") == "consultoria_gestion_bi":
        return False, "Es un servicio de consultoría"
    revisar = None if items else "El radar no trae sus ítems: revisa las bases"
    for it in items:
        producto, descripcion = normalizar(it.get("producto")), normalizar(it.get("descripcion"))
        m = (_SERVICIO_PRODUCTO.match(producto) or _SERVICIO_DESCRIPCION.search(descripcion)
             or _SOFTWARE.search(f"{producto} {descripcion}"))
        if m:
            return False, f"Línea {it.get('linea')}: incluye «{m.group(0)}», no es solo comprar y revender"
        if revisar is None and not item_concreto(it):
            revisar = f"Línea {it.get('linea')}: la cantidad o el producto exacto están en las bases"
    if revisar:
        return None, revisar
    return True, "Productos que se compran hechos y se revenden"


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
    cantidad y costo unitario neto; el lugar de entrega de la Compra Ágil si lo informa.
    Las líneas estimadas con OC del Estado van sin precio: nadie lo cotizó y no puede llegarle
    al proveedor como si fuera su precio."""
    items = []
    for it in p["items"]:
        if tienda and it.get("tienda") != tienda:
            continue
        descripcion = it.get("producto_mercado") or (
            it.get("descripcion") if es_compra_agil(lic) and it.get("descripcion") else it.get("producto"))
        costo = None if it.get("coincidencia") == ESTIMADA_OC else it.get("costo_unitario_neto")
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
