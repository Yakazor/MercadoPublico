"""Verifica los precios de mercado abriendo la página de cada tienda.

Uso:
    python scripts/verificar_precios.py [informes/mercado/*.json]

Las búsquedas de precios corren en un entorno que no puede abrir sitios .cl, así que
cada opción queda con "verificado": false. Este script corre en GitHub Actions, que sí
puede: abre cada link, busca el precio en la página (datos estructurados JSON-LD,
etiquetas meta/itemprop de precio o montos "$ 12.990" del texto) y lo compara con el
precio publicado de la opción. Solo marca "verificado": true si encuentra un monto a lo
más a un 3 % del publicado; si no, deja en "verificacion_pagina" qué encontró.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

import _ruta  # noqa: F401
from radar.config import hoy_chile, ruta_proyecto

TOLERANCIA = 0.03
PAUSA_MISMO_SITIO = 1.5
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "es-CL,es;q=0.9",
}

_JSON_PRECIO = re.compile(r'"(?:price|lowPrice|highPrice)"\s*:\s*"?(\d[\d.,]*)"?', re.I)
_META_PRECIO = re.compile(
    r'<meta[^>]+(?:property|itemprop|name)=["\'](?:product:price:amount|og:price:amount|price)["\'][^>]*'
    r'content=["\'](\d[\d.,]*)["\']', re.I)
_ITEMPROP = re.compile(r'itemprop=["\']price["\'][^>]*content=["\'](\d[\d.,]*)["\']', re.I)
_PESOS = re.compile(r"\$\s?(\d{1,3}(?:\.\d{3})+|\d{3,7})\b")


def _numero(texto: str) -> float | None:
    """'12.990' → 12990; '12990.00' → 12990; '12,990' → 12990 (precios en pesos)."""
    t = texto.strip()
    if re.fullmatch(r"\d+[.,]\d{1,2}", t):
        t = t.replace(",", ".")
    else:
        t = t.replace(".", "").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v > 0 else None


def precios_en_pagina(contenido: str) -> list[float]:
    """Montos que la página muestra como precio, de más a menos confiable."""
    contenido = html.unescape(contenido)
    vistos: list[float] = []
    for patron in (_JSON_PRECIO, _META_PRECIO, _ITEMPROP, _PESOS):
        for m in patron.finditer(contenido):
            v = _numero(m.group(1))
            if v and v not in vistos:
                vistos.append(v)
    return vistos


def comparar(precio_publicado: float, encontrados: list[float]) -> tuple[bool, float | None]:
    if not encontrados:
        return False, None
    cercano = min(encontrados, key=lambda v: abs(v - precio_publicado))
    return abs(cercano - precio_publicado) <= TOLERANCIA * precio_publicado, cercano


def _pesos(v: float) -> str:
    return "$" + f"{v:,.0f}".replace(",", ".")


def verificar_opcion(op: dict, sesion: requests.Session, hoy: str) -> dict:
    url = op.get("url")
    if not (isinstance(url, str) and url.startswith("https://")):
        return op
    try:
        precio = float(op.get("precio"))
    except (TypeError, ValueError):
        return op
    try:
        r = sesion.get(url, headers=CABECERAS, timeout=25)
    except requests.RequestException as e:
        op["verificacion_pagina"] = f"{hoy}: no se pudo abrir la página ({type(e).__name__})."
        return op
    if r.status_code != 200:
        op["verificacion_pagina"] = f"{hoy}: la tienda respondió HTTP {r.status_code}."
        return op
    ok, cercano = comparar(precio, precios_en_pagina(r.text))
    if ok:
        op["verificado"] = True
        op["verificado_en"] = hoy
        op["precio_pagina"] = cercano
        op["verificacion_pagina"] = f"{hoy}: la página muestra {_pesos(cercano)}."
    elif cercano is None:
        op["verificado"] = False
        op["verificacion_pagina"] = (f"{hoy}: la página abrió, pero no muestra el precio en el HTML "
                                     "(probablemente lo carga con JavaScript). Revísalo a mano.")
    else:
        op["verificado"] = False
        op["precio_pagina"] = cercano
        op["verificacion_pagina"] = (f"{hoy}: la página abrió y el precio más parecido es {_pesos(cercano)}, "
                                     f"no {_pesos(precio)}: puede haber cambiado.")
    return op


def verificar_archivo(ruta: Path, sesion: requests.Session, hoy: str) -> tuple[int, int]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    total = verificadas = 0
    ultimo: dict[str, float] = {}
    for item in datos.get("items", []):
        for op in item.get("opciones", []):
            sitio = urlparse(op.get("url") or "").netloc
            espera = PAUSA_MISMO_SITIO - (time.monotonic() - ultimo.get(sitio, 0))
            if sitio and espera > 0:
                time.sleep(espera)
            verificar_opcion(op, sesion, hoy)
            ultimo[sitio] = time.monotonic()
            total += 1
            verificadas += bool(op.get("verificado"))
    datos["verificacion_paginas"] = {"fecha": hoy, "opciones": total, "verificadas": verificadas}
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return total, verificadas


def main():
    rutas = [Path(a) for a in sys.argv[1:]] or sorted(ruta_proyecto("informes/mercado").glob("*.json"))
    hoy = hoy_chile().isoformat()
    sesion = requests.Session()
    for ruta in rutas:
        total, ok = verificar_archivo(ruta, sesion, hoy)
        print(f"{ruta.name}: {ok} de {total} opciones verificadas en la página de la tienda")


if __name__ == "__main__":
    main()
