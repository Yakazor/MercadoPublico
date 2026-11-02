"""Proveedores para una licitación o Compra Ágil: búsqueda en la web con Claude y solicitud de cotización.

La plataforma busca proveedores al abrir la ficha (si tiene la clave de la API de Claude) y
deja listo el correo para pedir la cotización formal. Aquí queda lo que no depende de Streamlit:

- `buscar(lic, items, clave_api)`: Claude busca en la web (búsqueda y lectura de páginas) proveedores
  chilenos de lo que se pide y devuelve una lista estructurada. Nunca se inventan datos de contacto:
  un correo o teléfono queda solo si aparece en una página que Claude leyó en esa búsqueda
  (`depurar`); si no, va como «por confirmar».
- Precios: en la misma búsqueda Claude abre las páginas de producto y trae hasta
  `precios_por_linea` alternativas por línea, de fuentes distintas. Un precio queda solo si aparece
  escrito en la página que Claude leyó (`depurar_precios`); queda en el formato de `mercado.json`
  (precio unitario neto) y la evaluación usa el más barato de cada línea: el que deja más margen.
- `leer(codigo)` y `guardar(codigo, datos, token)`: la búsqueda queda en la rama `proveedores` del
  repositorio (un JSON por licitación) para no pagarla dos veces. Esa rama no la toca el radar
  (la rama `datos` se reemplaza entera en cada publicación).
- `solicitud(lic, items, proveedor, remitente, hoy)`: asunto y cuerpo del correo para pedir la
  cotización formal, con las líneas que cubre ese proveedor; `enlace_gmail` y `enlace_correo`
  lo abren listo para revisar y enviar. Nada se envía solo.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

import requests

from .actualizacion import _cabeceras
from .config import cargar_config

CHILE = ZoneInfo("America/Santiago")
REPO = "Yakazor/MercadoPublico"
API_GITHUB = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CARPETA = "proveedores"
TIPOS = ["fabricante", "importador", "distribuidor mayorista", "tienda", "otro"]
COINCIDENCIAS = ["exacta", "equivalente", "aproximada"]
IVA = 0.19
INDICE_PRECIOS = "precios.json"   # {código: [precios]} de todas las búsquedas, para la evaluación
ORIGEN_PRECIO = "Búsqueda con Claude"
CONFIG = {
    "modelo": "claude-opus-5-5",
    "esfuerzo": "medium",
    "max_busquedas": 8,
    "max_paginas": 12,
    "maximo": 6,
    "precios_por_linea": 3,
    "buscar_al_abrir": True,
    "maximo_al_abrir_por_sesion": 10,
    "rama": "proveedores",
    "precio_usd": {"entrada_mtok": 4.0, "salida_mtok": 20.0, "busqueda": 0.01},
}
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_NULO = {"anyOf": [{"type": "string"}, {"type": "null"}]}
ESQUEMA = {
    "type": "object",
    "properties": {
        "proveedores": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string"},
                "tipo": {"type": "string", "enum": TIPOS},
                "lineas": {"type": "array", "items": {"type": "integer"}},
                "productos": {"type": "string"},
                "web": _NULO, "correo": _NULO, "telefono": _NULO, "ciudad": _NULO,
                "fuente": {"type": "string"},
                "nota": _NULO,
            },
            "required": ["nombre", "tipo", "lineas", "productos", "web", "correo", "telefono", "ciudad", "fuente",
                         "nota"],
            "additionalProperties": False,
        }},
        "precios": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "linea": {"type": "integer"},
                "proveedor": {"type": "string"},
                "producto": {"type": "string"},
                "precio": {"type": "number"},
                "iva_incluido": {"type": "boolean"},
                "unidades": {"type": "number"},
                "coincidencia": {"type": "string", "enum": COINCIDENCIAS},
                "url": {"type": "string"},
                "nota": _NULO,
            },
            "required": ["linea", "proveedor", "producto", "precio", "iva_incluido", "unidades", "coincidencia",
                         "url", "nota"],
            "additionalProperties": False,
        }},
        "resumen": {"type": "string"},
    },
    "required": ["proveedores", "precios", "resumen"],
    "additionalProperties": False,
}


class ErrorBusqueda(Exception):
    pass


class ErrorGitHub(Exception):
    pass


def configuracion() -> dict:
    """`config.yaml > proveedores` sobre los valores por defecto."""
    propia = cargar_config().get("proveedores") or {}
    return CONFIG | propia | {"precio_usd": CONFIG["precio_usd"] | (propia.get("precio_usd") or {})}


def _destino(lic: dict) -> str:
    return ", ".join(x for x in (lic.get("direccion_entrega"), lic.get("comuna"), lic.get("region")) if x) or "Chile"


def pedido(lic: dict, items: list[dict], cfg: dict | None = None) -> str:
    """Lo que se le pide a Claude: los ítems, dónde se entregan y las reglas de la búsqueda."""
    cfg = cfg or configuracion()
    lineas = []
    for it in items[:40]:
        cant = f"{it['cantidad']:g} {it.get('unidad') or ''}".strip() if it.get("cantidad") is not None else ""
        desc = " ".join(str(it.get("descripcion") or "").split())[:220]
        lineas.append(f"- Línea {it.get('linea')}: {it.get('producto') or ''} — {desc} ({cant})")
    if len(items) > 40:
        lineas.append(f"- … y {len(items) - 40} líneas más del mismo pedido.")
    tipo = "Compra Ágil" if lic.get("tipo") == "Compra Ágil" else "licitación"
    return (
        f"Soy proveedora del Estado de Chile y quiero ofertar en esta {tipo} de Mercado Público comprando los "
        f"productos hechos y revendiéndolos. Busca a quién comprárselos.\n\n"
        f"{tipo.capitalize()}: {lic.get('codigo')} — {lic.get('nombre') or ''}\n"
        f"Comprador: {lic.get('organismo') or '—'}\nEntrega en: {_destino(lic)}\n\nProductos pedidos:\n"
        + "\n".join(lineas) + "\n\n"
        f"Encuentra hasta {cfg['maximo']} proveedores en Chile (fabricantes, importadores, distribuidores "
        "mayoristas o tiendas que vendan a empresas) que puedan cotizar estos productos. Prefiere a los que "
        "cubren más líneas, a los que venden por volumen y a los que están en la región de entrega o en "
        "Santiago. Excluye vendedores particulares, avisos clasificados y tiendas sin despacho en Chile.\n\n"
        "Reglas:\n"
        "- Usa la búsqueda web en español y en el mercado chileno (.cl).\n"
        "- Para el correo y el teléfono abre la página de contacto del proveedor (lectura de páginas) y copia "
        "el dato tal como aparece. Si no lo ves escrito en una página, deja el campo en null: nunca lo "
        "deduzcas ni armes uno del tipo ventas@dominio.\n"
        "- «fuente» es la URL exacta de la página donde viste al proveedor o su contacto.\n"
        "- «lineas» son los números de línea del pedido que ese proveedor vende.\n"
        "- «productos»: qué vende de lo pedido, en una frase; «nota»: lo que conviene saber (mínimo de compra, "
        "despacho a regiones, si hay que pedir cotización por formulario).\n"
        "\n\nPrecios (el objetivo es el costo más bajo, para tener el mayor margen):\n"
        f"- En «precios» trae hasta {cfg['precios_por_linea']} alternativas por línea, de proveedores o tiendas "
        "distintas, empezando por las más baratas. Si no alcanzan las búsquedas para todas, prioriza las líneas "
        "de mayor cantidad.\n"
        "- Abre la página del producto (lectura de páginas) y copia el precio tal como aparece escrito en ella, "
        "en pesos chilenos. Nunca estimes ni calcules un precio: si no lo ves escrito, no lo pongas.\n"
        "- «url» es la página del producto donde aparece ese precio; «iva_incluido»: true si el precio es con "
        "IVA (lo normal en tiendas), false si la página dice «+ IVA» o «neto».\n"
        "- «unidades»: cuántas unidades de las que pide el comprador cubre ese precio (1 si es por unidad; 12 si "
        "es una caja de 12 y se piden unidades).\n"
        "- «coincidencia»: exacta (el mismo producto), equivalente (cumple todo lo pedido, otra marca) o "
        "aproximada (le falta algo de lo pedido: dilo en «nota»).\n"
        "- «resumen»: dos frases sobre qué tan fácil es abastecer este pedido y qué líneas quedaron sin "
        "proveedor o sin precio."
    )


def _usuario_chile() -> dict:
    return {"type": "approximate", "country": "CL", "city": "Santiago", "timezone": "America/Santiago"}


def _a_dict(bloque) -> dict:
    if isinstance(bloque, dict):
        return bloque
    return bloque.model_dump() if hasattr(bloque, "model_dump") else dict(bloque)


# Campos de los resultados que no son texto de una página: contenido cifrado (base64, con dígitos al
# azar) e identificadores.
_NO_ES_TEXTO = {"encrypted_content", "encrypted_index", "tool_use_id", "id", "type", "page_age", "media_type"}


def _recorrer(valor, textos: list[str], urls: set[str]) -> None:
    if isinstance(valor, dict):
        for clave, v in valor.items():
            if clave == "url" and isinstance(v, str):
                urls.add(v)
            if clave not in _NO_ES_TEXTO:
                _recorrer(v, textos, urls)
    elif isinstance(valor, list):
        for v in valor:
            _recorrer(v, textos, urls)
    elif isinstance(valor, str):
        textos.append(valor)


def evidencia(bloques: list) -> tuple[str, set[str]]:
    """Texto y URLs de lo que devolvieron las herramientas (resultados de búsqueda, páginas leídas y
    su filtrado). No cuenta lo que escribió Claude: su respuesta, su razonamiento ni las consultas que
    hizo (una consulta «ventas@empresa.cl» no prueba que ese correo exista)."""
    textos: list[str] = []
    urls: set[str] = set()
    for b in bloques:
        d = _a_dict(b)
        if str(d.get("type", "")).endswith("_tool_result"):
            _recorrer(d, textos, urls)
    return "\n".join(textos), urls


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _dominio(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _correo_en(correo: str, texto: str) -> bool:
    """El correo completo, no como parte de otro («to@x.cl» no está en «contacto@x.cl»)."""
    return re.search(rf"(?<![\w.+-]){re.escape(correo)}(?![\w-])", texto, re.I) is not None


def _telefono_en(telefono: str, texto: str) -> bool:
    """Los últimos 8 dígitos seguidos (con espacios, puntos, guiones o paréntesis entre ellos) en un
    mismo texto: no se juntan cifras de precios o códigos distintos."""
    digitos = _solo_digitos(telefono)
    if len(digitos) < 8:
        return False
    patron = r"[ .()\-]?".join(digitos[-8:])
    return re.search(rf"(?<!\d){patron}(?!\d)", texto) is not None


def depurar(proveedores: list[dict], texto: str, urls: set[str]) -> list[dict]:
    """Deja solo los datos que se pueden respaldar con lo que se leyó en la búsqueda.

    Un correo queda si aparece escrito (completo) en lo que devolvieron las herramientas; un teléfono,
    si sus últimos 8 dígitos aparecen seguidos en un mismo texto.
    Una fuente o web que no es un link (http/https) se descarta. `verificado` = la fuente es una de las páginas
    que devolvió la búsqueda."""
    dominios = {_dominio(u) for u in urls}
    limpios = []
    for p in proveedores:
        if not isinstance(p, dict):
            continue
        p = dict(p)
        avisos = []
        correo = str(p.get("correo") or "").strip()
        if correo and not (_CORREO.fullmatch(correo) and _correo_en(correo, texto)):
            p["correo"] = None
            avisos.append("correo por confirmar")
        telefono = str(p.get("telefono") or "").strip()
        if telefono and not _telefono_en(telefono, texto):
            p["telefono"] = None
            avisos.append("teléfono por confirmar")
        for campo in ("web", "fuente"):
            if p.get(campo) and not str(p[campo]).startswith(("https://", "http://")):
                p[campo] = None
        p["verificado"] = bool(p.get("fuente")) and (p["fuente"] in urls or _dominio(p["fuente"]) in dominios)
        if avisos:
            p["nota"] = "; ".join(x for x in (p.get("nota"), *avisos) if x)
        lineas = p.get("lineas") if isinstance(p.get("lineas"), list) else []
        p["lineas"] = sorted({int(x) for x in lineas if isinstance(x, int) or str(x).isdigit()})
        if p.get("nombre"):
            limpios.append(p)
    return limpios


def _cliente(clave_api: str):
    import anthropic   # solo se necesita para buscar
    return anthropic.Anthropic(api_key=clave_api, timeout=300, max_retries=2)


def _rechazos() -> tuple:
    """Errores 400 de la API (pedido no aceptado, no se cobra): se reintenta con un pedido más simple."""
    try:
        import anthropic
    except ImportError:
        return ()
    return (anthropic.BadRequestError,)


def _json_del_texto(texto: str) -> dict | None:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio < 0 or fin <= inicio:
            return None
        try:
            return json.loads(texto[inicio:fin + 1])
        except json.JSONDecodeError:
            return None


_SOLO_JSON = ("\n\nResponde solo con un objeto JSON, sin texto antes ni después, con esta forma: "
              '{"resumen": "...", "proveedores": [{"nombre", "tipo", "lineas", "productos", "web", "correo", '
              '"telefono", "ciudad", "fuente", "nota"}]} (null donde no haya dato).')


def _pedidos(cliente, cfg: dict, herramientas: list[dict]) -> list:
    """Del pedido más completo al más simple: con respaldo de modelo (si Claude Opus rechaza la
    petición, la retoma otro modelo) y JSON garantizado; sin respaldo; y sin el formato JSON."""
    formato = {"effort": cfg["esfuerzo"], "format": {"type": "json_schema", "schema": ESQUEMA}}
    base = {"model": cfg["modelo"], "max_tokens": 16000, "tools": herramientas}
    return [
        (cliente.beta.messages.create, base | {"output_config": formato, "betas": ["server-side-fallback-2026-07-01"],
                                               "fallbacks": "default"}, False),
        (cliente.messages.create, base | {"output_config": formato}, False),
        (cliente.messages.create, base | {"output_config": {"effort": cfg["esfuerzo"]}}, True),
    ]


def _conversar(crear, opciones: dict, texto: str) -> tuple:
    """Un pedido completo: si el servidor pausa su ciclo de herramientas («pause_turn»), se
    reenvía la conversación para que siga. Devuelve la última respuesta, los bloques y el uso."""
    mensajes = [{"role": "user", "content": texto}]
    bloques, uso = [], {"entrada": 0, "salida": 0, "busquedas": 0}
    respuesta = None
    for _ in range(4):
        respuesta = crear(messages=mensajes, **opciones)
        bloques += list(respuesta.content)
        u = respuesta.usage
        uso["entrada"] += (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        uso["salida"] += u.output_tokens or 0
        uso["busquedas"] += getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        if respuesta.stop_reason != "pause_turn":
            break
        mensajes.append({"role": "assistant", "content": respuesta.content})
    return respuesta, bloques, uso


def _precio_en(precio: float, texto: str) -> bool:
    """El precio escrito en la página: 14.990, 14990 o 14,990 (con o sin decimales), no como parte
    de otro número."""
    n = int(round(precio))
    formas = {str(n), f"{n:,}".replace(",", "."), f"{n:,}"}
    patron = "|".join(re.escape(f) for f in sorted(formas, key=len, reverse=True))
    return re.search(rf"(?<![\d.,])(?:{patron})(?!\d)(?![.,]\d{{3}})", texto) is not None


def _numero(valor) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def depurar_precios(precios: list, texto: str, urls: set[str], items: list[dict], codigo: str | None,
                    fecha: str) -> list[dict]:
    """Los precios que se pueden respaldar, en el formato de `mercado.json` (precio unitario neto).

    Queda un precio si su línea existe, la URL es un link y el número aparece escrito en lo que
    devolvieron las herramientas. `verificado` = la URL es una de las páginas que se leyeron.
    Por línea quedan ordenados del más barato al más caro."""
    lineas = {it.get("linea") for it in items}
    limpios = []
    for p in precios if isinstance(precios, list) else []:
        if not isinstance(p, dict):
            continue
        precio, unidades = _numero(p.get("precio")), _numero(p.get("unidades")) or 1.0
        url = str(p.get("url") or "")
        linea = p.get("linea")
        if (precio is None or linea not in lineas or not url.startswith(("https://", "http://"))
                or not _precio_en(precio, texto)):
            continue
        iva = p.get("iva_incluido") is not False
        coincidencia = p.get("coincidencia") if p.get("coincidencia") in COINCIDENCIAS else "aproximada"
        limpios.append({
            "codigo": codigo, "linea": linea, "tienda": str(p.get("proveedor") or _dominio(url)),
            "producto_mercado": str(p.get("producto") or ""), "url": url, "precio": precio, "iva_incluido": iva,
            "unidades_equivalentes": unidades,
            "precio_unitario_neto": round(precio / (1 + IVA if iva else 1) / unidades, 2),
            "coincidencia": coincidencia, "verificado": url in urls, "fecha_consulta": fecha[:10],
            "nota": p.get("nota") or None, "origen": ORIGEN_PRECIO,
        })
    limpios.sort(key=lambda m: (m["linea"], m["precio_unitario_neto"]))
    for n, m in enumerate(limpios, 1):
        m["clave"], m["opcion"] = f"{codigo}|{m['linea']}|c{n}", n
    return limpios


def buscar(lic: dict, items: list[dict], clave_api: str, cfg: dict | None = None, cliente=None,
           ahora: datetime | None = None) -> dict:
    """Busca proveedores con Claude (búsqueda web) y devuelve el resultado listo para guardar."""
    cfg = cfg or configuracion()
    cliente = cliente or _cliente(clave_api)
    herramientas = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": cfg["max_busquedas"],
         "user_location": _usuario_chile()},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": cfg["max_paginas"]},
    ]
    texto_pedido = pedido(lic, items, cfg)
    for crear, opciones, pedir_json in _pedidos(cliente, cfg, herramientas):
        try:
            respuesta, bloques, uso = _conversar(crear, opciones, texto_pedido + (_SOLO_JSON if pedir_json else ""))
            break
        except _rechazos():   # 400: la API no aceptó estas opciones (no se cobra); se prueba más simple
            continue
    else:
        raise ErrorBusqueda("La API de Claude no aceptó la búsqueda. Intenta de nuevo más tarde.")
    if respuesta is None or respuesta.stop_reason == "refusal":
        raise ErrorBusqueda("Claude no hizo esta búsqueda (la rechazó). Intenta de nuevo más tarde.")
    if respuesta.stop_reason == "max_tokens":
        raise ErrorBusqueda("La respuesta quedó cortada. Intenta de nuevo.")
    textos = [b.text for b in respuesta.content if getattr(b, "type", "") == "text"]
    datos = _json_del_texto(textos[-1]) if textos else None
    if not isinstance(datos, dict):
        raise ErrorBusqueda("No se pudo leer la lista de proveedores. Intenta de nuevo.")
    texto, urls = evidencia(bloques)
    fecha = (ahora or datetime.now(CHILE)).isoformat(timespec="minutes")
    precio = cfg["precio_usd"]
    costo = (uso["entrada"] * precio["entrada_mtok"] + uso["salida"] * precio["salida_mtok"]) / 1e6 \
        + uso["busquedas"] * precio["busqueda"]
    return {
        "codigo": lic.get("codigo"),
        "fecha": fecha,
        "modelo": getattr(respuesta, "model", cfg["modelo"]),
        "busquedas": uso["busquedas"], "costo_usd": round(costo, 2),
        "resumen": datos.get("resumen") or "",
        "proveedores": depurar(datos.get("proveedores") if isinstance(datos.get("proveedores"), list) else [],
                               texto, urls)[: cfg["maximo"]],
        "precios": depurar_precios(datos.get("precios"), texto, urls, items, lic.get("codigo"), fecha),
    }


# --- Rama `proveedores` del repositorio --------------------------------------------------------

def _error(r: requests.Response) -> ErrorGitHub:
    if r.status_code == 401:
        return ErrorGitHub("GitHub rechazó el token (vencido o mal copiado).")
    if r.status_code in (403, 404):
        return ErrorGitHub("El token de GitHub no tiene permiso «Contents: Read and write» sobre el repositorio.")
    return ErrorGitHub(f"GitHub respondió HTTP {r.status_code}.")


def leer(codigo: str, repo: str = REPO, rama: str | None = None, timeout: float = 15) -> dict | None:
    """La búsqueda guardada para esa licitación (None si no hay o GitHub no responde)."""
    rama = rama or configuracion()["rama"]
    try:
        r = requests.get(f"{RAW}/{repo}/{rama}/{CARPETA}/{codigo}.json", timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        datos = r.json()
    except ValueError:
        return None
    ok = isinstance(datos, dict) and datos.get("codigo") == codigo and isinstance(datos.get("proveedores"), list)
    return datos if ok else None


def _crear_rama(token: str, repo: str, rama: str, timeout: float) -> None:
    """Rama huérfana (sin el código): un push ahí no lanza los workflows ni reinicia la plataforma."""
    leeme = ("# Proveedores encontrados por la plataforma\n\nUn JSON por licitación o Compra Ágil "
             "(`proveedores/<código>.json`). Lo escribe la plataforma al buscar proveedores.\n")
    r = requests.post(f"{API_GITHUB}/repos/{repo}/git/blobs", json={"content": leeme, "encoding": "utf-8"},
                      headers=_cabeceras(token), timeout=timeout)
    if r.status_code != 201:
        raise _error(r)
    arbol = requests.post(f"{API_GITHUB}/repos/{repo}/git/trees", headers=_cabeceras(token), timeout=timeout,
                          json={"tree": [{"path": "README.md", "mode": "100644", "type": "blob",
                                          "sha": r.json()["sha"]}]})
    if arbol.status_code != 201:
        raise _error(arbol)
    commit = requests.post(f"{API_GITHUB}/repos/{repo}/git/commits", headers=_cabeceras(token), timeout=timeout,
                           json={"message": "Rama de proveedores", "tree": arbol.json()["sha"], "parents": []})
    if commit.status_code != 201:
        raise _error(commit)
    ref = requests.post(f"{API_GITHUB}/repos/{repo}/git/refs", headers=_cabeceras(token), timeout=timeout,
                        json={"ref": f"refs/heads/{rama}", "sha": commit.json()["sha"]})
    if ref.status_code not in (201, 422):   # 422: otra sesión la creó recién
        raise _error(ref)


def _asegurar_rama(token: str, repo: str, rama: str, timeout: float) -> None:
    existe = requests.get(f"{API_GITHUB}/repos/{repo}/branches/{rama}", headers=_cabeceras(token), timeout=timeout)
    if existe.status_code == 404:
        _crear_rama(token, repo, rama, timeout)
    elif existe.status_code != 200:
        raise _error(existe)


def _escribir(ruta: str, contenido, mensaje: str, token: str, repo: str, rama: str, timeout: float,
              intentos: int = 2) -> None:
    """Escribe un JSON en la rama. `contenido` puede ser una función que recibe lo que había (o None) y
    devuelve lo nuevo: si otra sesión escribió entremedio (409), se vuelve a leer y se reintenta."""
    url = f"{API_GITHUB}/repos/{repo}/contents/{ruta}"
    for intento in range(intentos):
        actual = requests.get(url, params={"ref": rama}, headers=_cabeceras(token), timeout=timeout)
        previo = None
        if actual.status_code == 404:
            _asegurar_rama(token, repo, rama, timeout)
        elif actual.status_code != 200:
            raise _error(actual)
        else:
            try:
                previo = json.loads(base64.b64decode(actual.json().get("content") or ""))
            except ValueError:
                previo = None
        datos = contenido(previo) if callable(contenido) else contenido
        cuerpo = {"message": mensaje, "branch": rama,
                  "content": base64.b64encode(json.dumps(datos, ensure_ascii=False, indent=1).encode()).decode()}
        if actual.status_code == 200:
            cuerpo["sha"] = actual.json().get("sha")
        r = requests.put(url, json=cuerpo, headers=_cabeceras(token), timeout=timeout)
        if r.status_code in (200, 201):
            return
        if r.status_code not in (409, 422) or intento == intentos - 1:
            raise _error(r)


def guardar(codigo: str, datos: dict, token: str | None, repo: str = REPO, rama: str | None = None,
            timeout: float = 20) -> None:
    """Escribe `proveedores/<código>.json` en la rama (la crea la primera vez) y pone sus precios en
    `proveedores/precios.json`, el índice que lee la evaluación."""
    if not token:
        raise ErrorGitHub("Falta el token de GitHub (secreto github_token).")
    rama = rama or configuracion()["rama"]
    _escribir(f"{CARPETA}/{codigo}.json", datos, f"Proveedores para {codigo} (plataforma)", token, repo, rama,
              timeout)
    precios = datos.get("precios") or []

    def indice(previo):
        previo = previo if isinstance(previo, dict) else {}
        if precios:
            previo[codigo] = precios
        else:
            previo.pop(codigo, None)
        return previo

    _escribir(f"{CARPETA}/{INDICE_PRECIOS}", indice, f"Precios de {codigo} (plataforma)", token, repo, rama,
              timeout)


def leer_precios(repo: str = REPO, rama: str | None = None, timeout: float = 15) -> dict:
    """{código: [precios]} de todas las búsquedas guardadas ({} si no hay o GitHub no responde)."""
    rama = rama or configuracion()["rama"]
    try:
        r = requests.get(f"{RAW}/{repo}/{rama}/{CARPETA}/{INDICE_PRECIOS}", timeout=timeout)
        datos = r.json() if r.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {codigo: [m for m in lista if isinstance(m, dict)] for codigo, lista in datos.items()
            if isinstance(lista, list)}


# --- Solicitud de cotización --------------------------------------------------------------------

def responder_antes(lic: dict, hoy: date) -> date:
    """Dos días antes del cierre, sin pasar de hoy + 3 ni quedar antes de mañana."""
    try:
        cierre = date.fromisoformat((lic.get("fecha_cierre") or "")[:10])
    except ValueError:
        cierre = hoy + timedelta(5)
    return max(hoy + timedelta(1), min(cierre - timedelta(2), hoy + timedelta(3)))


def nombre_item(it: dict, largo: int = 300) -> str:
    """Lo que pide el comprador: su descripción. El producto ONU es solo la categoría y a veces no
    calza («Perchas de ropa» para un pantalón cargo): se usa cuando no hay descripción."""
    return " ".join(str(it.get("descripcion") or "").split())[:largo] or it.get("producto") or ""


def _linea(it: dict, n: int) -> str:
    cant = f"{it['cantidad']:g} {it.get('unidad') or ''}".strip() if it.get("cantidad") is not None else "—"
    return f"{n}. {nombre_item(it)} — Cantidad: {cant}"


def solicitud(lic: dict, items: list[dict], proveedor: dict | None, remitente: dict, hoy: date,
              lineas: list | None = None) -> dict:
    """{para, asunto, cuerpo} del correo para pedir la cotización formal a un proveedor.

    `lineas`: las que se piden (por defecto, las que cubre el proveedor; si no se sabe, todas)."""
    proveedor = proveedor or {}
    elegidas = set(lineas if lineas is not None else proveedor.get("lineas") or [])
    pedidos = [it for it in items if not elegidas or it.get("linea") in elegidas] or items
    agil = lic.get("tipo") == "Compra Ágil"
    nombre = proveedor.get("nombre") or "[Proveedor]"
    try:
        cierre_txt = date.fromisoformat((lic.get("fecha_cierre") or "")[:10]).strftime("%d-%m-%Y")
    except ValueError:
        cierre_txt = "próximamente"
    entrega = _destino(lic)
    plazo = lic.get("plazo_entrega_dias")
    firma = [x for x in (remitente.get("nombre"), remitente.get("cargo"), remitente.get("empresa"),
                         remitente.get("contacto")) if x]
    cuerpo = [
        f"Estimados/as {nombre}:", "",
        "Junto con saludar, les escribo porque estamos preparando una oferta para "
        + ("una Compra Ágil" if agil else "una licitación") + f" de Mercado Público ({lic.get('codigo')}) "
        f"de {lic.get('organismo') or 'un organismo público'}, con entrega en {entrega}.", "",
        "Les solicitamos una cotización formal por los siguientes productos:", "",
        *[_linea(it, n) for n, it in enumerate(pedidos, 1)], "",
        "Por favor, indiquen en la cotización:",
        "- Precio unitario y total, señalando si incluye IVA.",
        "- Marca, modelo y ficha técnica de cada producto (o el equivalente que ofrezcan).",
        "- Stock disponible y plazo de entrega"
        + (f" (el comprador pide entrega en {plazo:g} días desde la orden de compra)." if plazo else "."),
        f"- Costo de despacho a {lic.get('comuna') or lic.get('region') or 'destino'}, o si el precio lo incluye.",
        "- Vigencia de la oferta, garantía y condiciones de pago.",
        "- Descuento por volumen, si aplica.", "",
        f"Necesitamos la cotización idealmente antes del {responder_antes(lic, hoy).strftime('%d-%m-%Y')}, "
        f"ya que el proceso cierra el {cierre_txt}.", "",
        "Quedamos atentos. Saludos cordiales,", *firma,
    ]
    return {"para": proveedor.get("correo") or "", "asunto": f"Solicitud de cotización – {lic.get('codigo')} – "
            f"{' '.join(str(lic.get('nombre') or '').split())[:80]}", "cuerpo": "\n".join(cuerpo)}


def enlace_gmail(correo: dict) -> str:
    """Abre el correo en Gmail (redactar), listo para revisar y enviar."""
    return "https://mail.google.com/mail/?" + urlencode(
        {"view": "cm", "fs": "1", "to": correo["para"], "su": correo["asunto"], "body": correo["cuerpo"]},
        quote_via=quote)


def enlace_correo(correo: dict) -> str:
    """mailto: abre el programa de correo del equipo (Outlook, Correo de Mac…)."""
    return f"mailto:{quote(correo['para'])}?subject={quote(correo['asunto'])}&body={quote(correo['cuerpo'])}"
