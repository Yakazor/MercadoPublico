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
- Sin la API: `pedido_chrome(lic, items)` es la instrucción para Claude en Chrome (la extensión del
  navegador, que usa el plan de Claude y no el saldo de la API) e `importar(lic, items, texto)` trae
  su respuesta. Como ahí no hay registro de lo que leyó, la plataforma abre las páginas para
  comprobar cada precio y cada contacto; lo que no se pudo comprobar queda marcado, nunca como cierto.
- `leer(codigo)` y `guardar(codigo, datos, token)`: la búsqueda queda en la rama `proveedores` del
  repositorio (un JSON por licitación) para no pagarla dos veces. Esa rama no la toca el radar
  (la rama `datos` se reemplaza entera en cada publicación).
- `solicitud(lic, items, proveedor, remitente, hoy)`: asunto y cuerpo del correo para pedir la
  cotización formal, con las líneas que cubre ese proveedor; `enlace_gmail` y `enlace_correo`
  lo abren listo para revisar y enviar. Nada se envía solo.
"""
from __future__ import annotations

import base64
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
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
ORIGEN_CHROME = "Claude en Chrome"   # búsqueda hecha en el navegador (plan de Claude, sin API)
PAGINAS_A_COMPROBAR = 30             # de una respuesta de Claude en Chrome, cuántas páginas se abren
NAVEGADOR = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "es-CL,es;q=0.9",
}
CONFIG = {
    "modelo": "claude-haiku-5-5",
    "esfuerzo": "medium",
    "max_busquedas": 5,
    "max_paginas": 6,
    "max_tokens_pagina": 8000,        # cada página leída se corta aquí (las de tienda traen menús y listados)
    "tope_usd_por_busqueda": 0.60,    # se corta la búsqueda si lo pasa
    "tope_usd_diario": 3.0,           # suma de todas las búsquedas del día en la plataforma
    "maximo": 6,
    "precios_por_linea": 3,
    "buscar_al_abrir": True,
    "maximo_al_abrir_por_dia": 10,
    "monto_minimo_al_abrir": 1_000_000,
    "rama": "proveedores",
    "precio_usd": {"busqueda": 0.01},
}
# US$ por millón de tokens (entrada, salida) de cada modelo. Claude Haiku 5.5 cobra más cuando una
# petición pasa de 100 mil tokens de entrada (lo normal al leer varias páginas).
TARIFAS = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
TARIFA_HAIKU_LARGA = (0.50, 2.50)


def _es_haiku(modelo: str) -> bool:
    return "haiku" in (modelo or "")


def herramientas(cfg: dict) -> list[dict]:
    """Búsqueda y lectura web. Con filtrado dinámico (menos tokens) en Opus y Sonnet; Claude Haiku 5.5
    solo acepta las versiones básicas."""
    basicas = _es_haiku(cfg["modelo"])
    return [
        {"type": "web_search_20250305" if basicas else "web_search_20260209", "name": "web_search",
         "max_uses": cfg["max_busquedas"], "user_location": _usuario_chile()},
        {"type": "web_fetch_20250910" if basicas else "web_fetch_20260209", "name": "web_fetch",
         "max_uses": cfg["max_paginas"], "max_content_tokens": cfg["max_tokens_pagina"]},
    ]


def costo_usd(modelo: str, usos: list[tuple[int, int]], busquedas: int, cfg: dict | None = None) -> float:
    """Costo aproximado: tokens de cada petición a la tarifa del modelo, más las búsquedas web. Si el
    modelo no está en TARIFAS se usa `precio_usd.entrada_mtok`/`salida_mtok` de config (o la de Opus)."""
    precio = (cfg or {}).get("precio_usd") or {}
    base = next((t for m, t in TARIFAS.items() if (modelo or "").startswith(m)),
                (precio.get("entrada_mtok", 4.0), precio.get("salida_mtok", 20.0)))
    total = 0.0
    for entrada, salida in usos:
        tarifa = TARIFA_HAIKU_LARGA if _es_haiku(modelo) and entrada > 100_000 else base
        total += (entrada * tarifa[0] + salida * tarifa[1]) / 1e6
    return total + busquedas * precio.get("busqueda", 0.01)
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
    """`costo_usd`: lo que alcanzó a gastar la búsqueda antes de cortarse (0 si la API la rechazó)."""
    def __init__(self, mensaje: str, costo_usd: float = 0.0):
        super().__init__(mensaje)
        self.costo_usd = costo_usd


class ErrorGitHub(Exception):
    pass


def configuracion() -> dict:
    """`config.yaml > proveedores` sobre los valores por defecto."""
    propia = cargar_config().get("proveedores") or {}
    return CONFIG | propia | {"precio_usd": CONFIG["precio_usd"] | (propia.get("precio_usd") or {})}


def _destino(lic: dict) -> str:
    return ", ".join(x for x in (lic.get("direccion_entrega"), lic.get("comuna"), lic.get("region")) if x) or "Chile"


def _encabezado(lic: dict, items: list[dict]) -> str:
    """Quién pregunta, qué licitación es y los productos pedidos: el comienzo de la instrucción."""
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
        + "\n".join(lineas) + "\n\n")


def pedido(lic: dict, items: list[dict], cfg: dict | None = None) -> str:
    """Lo que se le pide a Claude: los ítems, dónde se entregan y las reglas de la búsqueda."""
    cfg = cfg or configuracion()
    return (
        _encabezado(lic, items) +
        f"Encuentra hasta {cfg['maximo']} proveedores en Chile (fabricantes, importadores, distribuidores "
        "mayoristas o tiendas que vendan a empresas) que puedan cotizar estos productos. Prefiere a los que "
        "cubren más líneas, a los que venden por volumen y a los que están en la región de entrega o en "
        "Santiago. Excluye vendedores particulares, avisos clasificados y tiendas sin despacho en Chile.\n\n"
        f"Cómo trabajar (presupuesto limitado: {cfg['max_busquedas']} búsquedas y {cfg['max_paginas']} páginas "
        "en total, cada una cuesta):\n"
        "1. Planifica antes de buscar: agrupa las líneas parecidas (p. ej. todas las de ferretería) y haz una "
        "búsqueda por grupo, no una por línea. Usa el nombre genérico del producto y la medida clave, en "
        "español, sin marcas salvo que el pedido exija una.\n"
        "2. Prefiere tiendas que venden varias líneas del pedido (un proveedor que cubre 5 líneas vale más que "
        "5 proveedores de una).\n"
        "3. Abre solo páginas de producto (con precio) o de contacto. No abras portadas, categorías, "
        "resultados de búsqueda internos, PDF ni catálogos largos. Si un resultado de búsqueda ya muestra el "
        "precio y la URL del producto, igual abre esa página: solo vale el precio escrito en una página abierta.\n"
        "4. No repitas búsquedas parecidas ni abras dos veces la misma página. Cuando tengas un precio para "
        "las líneas de mayor cantidad, termina: es mejor una respuesta parcial que agotar el presupuesto.\n\n"
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


_FORMA_CHROME = """{
  "resumen": "dos frases: qué tan fácil es abastecer el pedido y qué líneas quedaron sin precio",
  "proveedores": [
    {"nombre": "", "tipo": "fabricante | importador | distribuidor mayorista | tienda | otro",
     "lineas": [1, 2], "productos": "", "web": "", "correo": null, "telefono": null, "ciudad": null,
     "fuente": "", "nota": null}
  ],
  "precios": [
    {"linea": 1, "proveedor": "", "producto": "", "precio": 14990, "iva_incluido": true, "unidades": 1,
     "coincidencia": "exacta | equivalente | aproximada", "url": "", "nota": null}
  ]
}"""
CUADRO_CHROME = "Respuesta de Claude en Chrome"   # el cuadro de la plataforma donde se pega la respuesta
BOTON_CHROME = "Guardar precios"


def pedido_chrome(lic: dict, items: list[dict], cfg: dict | None = None) -> str:
    """La instrucción para Claude en Chrome (la extensión del navegador): la misma búsqueda, pero
    navegando las tiendas con el plan de Claude, sin gastar saldo de la API. Su respuesta (un JSON)
    se trae a la plataforma con `importar`."""
    cfg = cfg or configuracion()
    return (
        _encabezado(lic, items) +
        "Qué hacer (solo leer páginas: no inicies sesión, no agregues nada al carro, no llenes formularios "
        "y no compres nada):\n"
        "1. Busca en Google, en español y en tiendas o distribuidores de Chile (.cl), cada producto. Agrupa las "
        "líneas parecidas y usa el nombre genérico y la medida clave, sin marcas salvo que el pedido exija una.\n"
        f"2. Abre la página del producto y copia el precio tal como aparece escrito. Trae hasta "
        f"{cfg['precios_por_linea']} alternativas por línea, de tiendas distintas, empezando por las más baratas. "
        "Prefiere distribuidores mayoristas y tiendas que venden a empresas y que cubren varias líneas.\n"
        "3. Nunca estimes ni calcules un precio: si no lo ves escrito en la página de ese producto, no lo pongas.\n"
        f"4. De hasta {cfg['maximo']} proveedores, abre su página de contacto y copia el correo y el teléfono tal "
        "como aparecen. Si no los ves escritos, deja null: nunca armes uno del tipo ventas@dominio.\n"
        "5. Si las líneas son muchas, empieza por las de mayor cantidad y no abras más de unas 25 páginas: es "
        "mejor una respuesta parcial que una muy larga.\n\n"
        "Al terminar, responde solo con un bloque de código JSON con esta forma (null donde no haya dato):\n\n"
        + _FORMA_CHROME + "\n\n"
        "Campos:\n"
        "- «precio»: número entero en pesos chilenos, sin puntos, comas ni signo (14990, no 14.990).\n"
        "- «iva_incluido»: true si el precio es con IVA (lo normal en tiendas), false si la página dice «+ IVA» "
        "o «neto».\n"
        "- «unidades»: cuántas unidades de las que pide el comprador cubre ese precio (1 si es por unidad; 12 si "
        "es una caja de 12 y se piden unidades).\n"
        "- «coincidencia»: exacta (el mismo producto), equivalente (cumple todo lo pedido, otra marca) o "
        "aproximada (le falta algo de lo pedido: dilo en «nota»).\n"
        "- «url»: la página del producto donde está escrito ese precio; «fuente»: la página donde viste al "
        "proveedor o su contacto. Copia los links completos, tal como están en la barra de direcciones.\n"
        "- «lineas»: los números de línea del pedido que ese proveedor vende; «nota»: lo que conviene saber "
        "(mínimo de compra, despacho a regiones, si hay que pedir cotización por formulario).\n\n"
        f"Para terminar: si la pestaña «Radar Mercado Público» sigue abierta, pega el JSON en el cuadro "
        f"«{CUADRO_CHROME}» y aprieta «{BOTON_CHROME}». En esa página no toques ningún otro botón (hay uno "
        "que cobra). Si no puedes, deja el JSON en el chat y yo lo copio."
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


def paginas(bloques: list) -> dict[str, str]:
    """{url: texto} de cada página que Claude abrió (web_fetch): para comprobar que un precio está
    escrito en la página de ese producto y no en otra."""
    leidas: dict[str, str] = {}
    for b in bloques:
        d = _a_dict(b)
        if d.get("type") != "web_fetch_tool_result" or not isinstance(d.get("content"), dict):
            continue
        url = d["content"].get("url")
        if isinstance(url, str):
            textos: list[str] = []
            _recorrer(d["content"].get("content"), textos, set())
            leidas[url] = leidas.get(url, "") + "\n" + "\n".join(textos)
    return leidas


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


def depurar(proveedores: list[dict], texto: str, urls: set[str], conservar: bool = False) -> list[dict]:
    """Deja solo los datos que se pueden respaldar con lo que se leyó en la búsqueda.

    `conservar`: el correo o teléfono sin respaldo sale de su campo igual (no se usa para escribirle),
    pero queda a la vista en la nota, «por confirmar» (respuestas de Claude en Chrome: lo leyó en el
    navegador y la plataforma no pudo abrir esa página).

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
            avisos.append("correo por confirmar" + (f": {correo}" if conservar and _CORREO.fullmatch(correo) else ""))
        telefono = str(p.get("telefono") or "").strip()
        if telefono and not _telefono_en(telefono, texto):
            p["telefono"] = None
            avisos.append("teléfono por confirmar"
                          + (f": {telefono[:25]}" if conservar and len(_solo_digitos(telefono)) >= 8 else ""))
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
              '"telefono", "ciudad", "fuente", "nota"}], "precios": [{"linea", "proveedor", "producto", "precio", '
              '"iva_incluido", "unidades", "coincidencia", "url", "nota"}]} (null donde no haya dato).')


def _pedidos(cliente, cfg: dict, herramientas: list[dict]) -> list:
    """Del pedido más completo al más simple: con respaldo de modelo (si Claude rechaza la petición,
    la retoma otro modelo; Claude Haiku 5.5 no tiene respaldo) y JSON garantizado; sin respaldo; y sin
    el formato JSON."""
    formato = {"effort": cfg["esfuerzo"], "format": {"type": "json_schema", "schema": ESQUEMA}}
    base = {"model": cfg["modelo"], "max_tokens": 16000, "tools": herramientas}
    con_respaldo = [] if _es_haiku(cfg["modelo"]) else [
        (cliente.beta.messages.create, base | {"output_config": formato, "betas": ["server-side-fallback-2026-07-01"],
                                               "fallbacks": "default"}, False)]
    return con_respaldo + [
        (cliente.messages.create, base | {"output_config": formato}, False),
        (cliente.messages.create, base | {"output_config": {"effort": cfg["esfuerzo"]}}, True),
    ]


def _conversar(crear, opciones: dict, texto: str, cfg: dict | None = None) -> tuple:
    """Un pedido completo: si el servidor pausa su ciclo de herramientas («pause_turn»), se
    reenvía la conversación para que siga. Devuelve la última respuesta, los bloques y el uso.

    Cada ronda reenvía todo lo leído, así que el costo crece rápido: si lo gastado pasa
    `tope_usd_por_busqueda`, se corta (ErrorBusqueda con lo gastado). Si la API falla a mitad de
    camino, el error lleva `costo_usd` con lo que ya se había gastado."""
    cfg = cfg or {}
    tope = cfg.get("tope_usd_por_busqueda")
    mensajes = [{"role": "user", "content": texto}]
    bloques, uso = [], {"entrada": 0, "salida": 0, "busquedas": 0, "peticiones": []}
    respuesta = None
    for _ in range(4):
        try:
            respuesta = crear(messages=mensajes, **opciones)
        except Exception as e:
            if uso["peticiones"]:   # ya había gastado: que se sepa cuánto
                e.costo_usd = costo_usd(opciones.get("model", ""), uso["peticiones"], uso["busquedas"], cfg)
            raise
        bloques += list(respuesta.content)
        u = respuesta.usage
        entrada = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        uso["entrada"] += entrada
        uso["salida"] += u.output_tokens or 0
        uso["peticiones"].append((entrada, u.output_tokens or 0))
        uso["busquedas"] += getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        if respuesta.stop_reason != "pause_turn":
            break
        gastado = costo_usd(opciones.get("model", ""), uso["peticiones"], uso["busquedas"], cfg)
        if tope and gastado >= tope:
            raise ErrorBusqueda(f"Se detuvo al llegar al tope de US$ {tope:.2f} por búsqueda "
                                f"(gastó US$ {gastado:.2f}). Sube `proveedores.tope_usd_por_busqueda` si hace falta.",
                                gastado)
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


def _numerar(precios: list[dict], codigo: str | None) -> list[dict]:
    """Del más barato al más caro por línea, con su `clave` y número de opción."""
    precios.sort(key=lambda m: (m.get("linea") or 0, m.get("precio_unitario_neto") or 0))
    for n, m in enumerate(precios, 1):
        m["clave"], m["opcion"] = f"{codigo}|{m.get('linea')}|c{n}", n
    return precios


def depurar_precios(precios: list, texto: str | None, urls: set[str], items: list[dict], codigo: str | None,
                    fecha: str, leidas: dict[str, str] | None = None, origen: str = ORIGEN_PRECIO) -> list[dict]:
    """Los precios que se pueden respaldar, en el formato de `mercado.json` (precio unitario neto).

    Queda un precio si su línea existe, la URL es un link y el número aparece escrito en lo que
    devolvieron las herramientas (`texto`; con None no se exige: respuestas de Claude en Chrome, de
    las que no hay registro). `verificado` = la URL es una de las páginas que se leyeron (con
    `leidas`, las páginas abiertas: el precio además tiene que estar escrito en la de ese producto).
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
                or (texto is not None and not _precio_en(precio, texto))):
            continue
        iva = p.get("iva_incluido") is not False
        coincidencia = p.get("coincidencia") if p.get("coincidencia") in COINCIDENCIAS else "aproximada"
        limpios.append({
            "codigo": codigo, "linea": linea, "tienda": str(p.get("proveedor") or _dominio(url)),
            "producto_mercado": str(p.get("producto") or ""), "url": url, "precio": precio, "iva_incluido": iva,
            "unidades_equivalentes": unidades,
            "precio_unitario_neto": round(precio / (1 + IVA if iva else 1) / unidades, 2),
            "coincidencia": coincidencia,
            "verificado": url in leidas and _precio_en(precio, leidas[url]) if leidas is not None else url in urls, "fecha_consulta": fecha[:10],
            "nota": p.get("nota") or None, "origen": origen,
        })
    return _numerar(limpios, codigo)


def buscar(lic: dict, items: list[dict], clave_api: str, cfg: dict | None = None, cliente=None,
           ahora: datetime | None = None) -> dict:
    """Busca proveedores con Claude (búsqueda web) y devuelve el resultado listo para guardar."""
    cfg = cfg or configuracion()
    cliente = cliente or _cliente(clave_api)
    texto_pedido = pedido(lic, items, cfg)
    motivo, gastado = "", 0.0   # gastado: lo que cobraron intentos que fallaron a mitad de camino
    respuesta = None
    for crear, opciones, pedir_json in _pedidos(cliente, cfg, herramientas(cfg)):
        try:
            respuesta, bloques, uso = _conversar(crear, opciones, texto_pedido + (_SOLO_JSON if pedir_json else ""),
                                                 cfg)
            break
        except _rechazos() as e:   # 400: la API no aceptó estas opciones; se prueba más simple
            motivo = str(getattr(e, "message", "") or e)
            gastado += getattr(e, "costo_usd", 0.0)
            if "credit" in motivo.lower():   # sin saldo: los demás intentos también fallarían
                break
    if respuesta is None:
        sin_saldo = "credit" in motivo.lower()
        raise ErrorBusqueda(("Se acabó el saldo de la API de Claude: recarga en console.anthropic.com › Facturación."
                             if sin_saldo else "La API de Claude no aceptó la búsqueda"
                             + (f": {motivo[:300]}" if motivo else ".") + " Intenta de nuevo más tarde."), gastado)
    modelo = getattr(respuesta, "model", None) or cfg["modelo"]
    costo = gastado + costo_usd(modelo, uso["peticiones"], uso["busquedas"], cfg)
    if respuesta.stop_reason == "refusal":
        raise ErrorBusqueda("Claude no hizo esta búsqueda (la rechazó). Intenta de nuevo más tarde.", costo)
    if respuesta.stop_reason == "max_tokens":
        raise ErrorBusqueda("La respuesta quedó cortada. Intenta de nuevo.", costo)
    if respuesta.stop_reason == "pause_turn":
        raise ErrorBusqueda("La búsqueda no terminó en las rondas permitidas. Intenta de nuevo.", costo)
    textos = [b.text for b in respuesta.content if getattr(b, "type", "") == "text"]
    datos = _json_del_texto(textos[-1]) if textos else None
    if not isinstance(datos, dict):
        raise ErrorBusqueda("No se pudo leer la lista de proveedores. Intenta de nuevo.", costo)
    texto, urls = evidencia(bloques)
    fecha = (ahora or datetime.now(CHILE)).isoformat(timespec="minutes")
    return {
        "codigo": lic.get("codigo"),
        "fecha": fecha,
        "modelo": modelo,
        "busquedas": uso["busquedas"], "costo_usd": round(costo, 2),
        "tokens": {"entrada": uso["entrada"], "salida": uso["salida"]},
        "resumen": datos.get("resumen") or "",
        "proveedores": depurar(datos.get("proveedores") if isinstance(datos.get("proveedores"), list) else [],
                               texto, urls)[: cfg["maximo"]],
        "precios": depurar_precios(datos.get("precios"), texto, urls, items, lic.get("codigo"), fecha,
                                   paginas(bloques)),
    }


# --- Sin la API: la respuesta de Claude en Chrome ---------------------------------------------

# "precio": 14.990 (o "$14.990", o "14990") → 14990: como número JSON, 14.990 se leería 14,99 pesos.
_PRECIO_ESCRITO = re.compile(r'("precio"\s*:\s*)"?\$?\s*(\d{1,3}(?:[.,]\d{3})+|\d+)"?(?=\s*[,}])')


def _publica(url) -> bool:
    """Un link http(s) a un sitio con nombre de dominio: no una IP ni un equipo de la red interna."""
    if not str(url or "").startswith(("https://", "http://")):
        return False
    sitio = _dominio(url)
    return "." in sitio and ":" not in sitio and _solo_digitos(sitio) != sitio.replace(".", "")


def abrir_pagina(url: str, timeout: float = 10) -> str | None:
    """El contenido de una página (None si no abre), para comprobar lo que trajo Claude en Chrome."""
    try:
        r = requests.get(url, headers=NAVEGADOR, timeout=timeout)
    except requests.RequestException:
        return None
    return html.unescape(r.text) if r.status_code == 200 else None


def _abrir_paginas(urls: list, abrir, maximo: int = PAGINAS_A_COMPROBAR) -> dict[str, str]:
    """{url: contenido} de las que abrieron, varias a la vez y sin repetir."""
    unicas = list(dict.fromkeys(u for u in urls if _publica(u)))[:maximo]
    if not unicas:
        return {}
    with ThreadPoolExecutor(max_workers=8) as grupo:
        contenidos = list(grupo.map(abrir, unicas))
    return {u: c for u, c in zip(unicas, contenidos) if c}


def importar(lic: dict, items: list[dict], texto: str, cfg: dict | None = None, ahora: datetime | None = None,
             abrir=None) -> tuple[dict, int]:
    """La respuesta de Claude en Chrome como una búsqueda lista para guardar, sin costo de API.

    De esa búsqueda no hay registro de lo leído, así que la plataforma abre las páginas
    (`abrir(url)` → contenido o None) para comprobar. `verificado` = el precio está escrito en la
    página de ese producto; el que no se pudo comprobar queda sin la marca (muchas tiendas cargan el
    precio con JavaScript o no le responden a un servidor). Un correo o teléfono que no aparece en
    las páginas abiertas no se usa: queda en la nota, «por confirmar».

    Devuelve el resultado y cuántos precios se descartaron (línea que no existe, sin link o sin
    precio)."""
    cfg = cfg or configuracion()
    datos = _json_del_texto(_PRECIO_ESCRITO.sub(lambda m: m.group(1) + _solo_digitos(m.group(2)), texto or ""))
    listas = {k: [x for x in datos.get(k) if isinstance(x, dict)] if isinstance(datos, dict)
              and isinstance(datos.get(k), list) else [] for k in ("proveedores", "precios")}
    if not listas["proveedores"] and not listas["precios"]:
        raise ErrorBusqueda("No se pudo leer la respuesta: pega el bloque JSON completo que escribió Claude, "
                            "desde la primera { hasta la última }.")
    fecha = (ahora or datetime.now(CHILE)).isoformat(timespec="minutes")
    urls = [p.get("url") for p in listas["precios"]]
    urls += [p.get(campo) for p in listas["proveedores"][: cfg["maximo"]] for campo in ("fuente", "web")]
    leidas = _abrir_paginas(urls, abrir or abrir_pagina)
    precios = depurar_precios(listas["precios"], None, set(leidas), items, lic.get("codigo"), fecha, leidas,
                              origen=ORIGEN_CHROME)
    return {
        "codigo": lic.get("codigo"),
        "fecha": fecha,
        "modelo": ORIGEN_CHROME, "origen": "chrome",
        "busquedas": 0, "costo_usd": 0.0,
        "resumen": str(datos.get("resumen") or ""),
        "proveedores": depurar(listas["proveedores"], "\n".join(leidas.values()), set(leidas),
                               conservar=True)[: cfg["maximo"]],
        "precios": precios,
    }, len(listas["precios"]) - len(precios)


def sumar(previa: dict | None, nueva: dict) -> dict:
    """La búsqueda nueva sobre la que ya había: proveedores sin repetir (por nombre) y precios sin
    repetir (por línea y link), mandando lo nuevo; el costo y las búsquedas web se acumulan."""
    if not previa:
        return nueva

    def nombre(p: dict) -> str:
        return str(p.get("nombre") or "").strip().lower()

    nombres = {nombre(p) for p in nueva.get("proveedores") or []}
    vistos = {(m.get("linea"), m.get("url")) for m in nueva.get("precios") or []}
    precios = [dict(m) for m in (nueva.get("precios") or [])
               + [m for m in previa.get("precios") or [] if (m.get("linea"), m.get("url")) not in vistos]]
    return previa | nueva | {
        "proveedores": (nueva.get("proveedores") or [])
        + [p for p in previa.get("proveedores") or [] if nombre(p) not in nombres],
        "precios": _numerar(precios, nueva.get("codigo")),
        "busquedas": (previa.get("busquedas") or 0) + (nueva.get("busquedas") or 0),
        "costo_usd": round((previa.get("costo_usd") or 0) + (nueva.get("costo_usd") or 0), 2),
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
