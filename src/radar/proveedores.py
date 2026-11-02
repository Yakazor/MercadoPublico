"""Proveedores para una licitación o Compra Ágil: búsqueda en la web con Claude y solicitud de cotización.

La plataforma busca proveedores al abrir la ficha (si tiene la clave de la API de Claude) y
deja listo el correo para pedir la cotización formal. Aquí queda lo que no depende de Streamlit:

- `buscar(lic, items, clave_api)`: Claude busca en la web (búsqueda y lectura de páginas) proveedores
  chilenos de lo que se pide y devuelve una lista estructurada. Nunca se inventan datos de contacto:
  un correo o teléfono queda solo si aparece en una página que Claude leyó en esa búsqueda
  (`depurar`); si no, va como «por confirmar».
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

from .config import cargar_config

CHILE = ZoneInfo("America/Santiago")
REPO = "Yakazor/MercadoPublico"
API_GITHUB = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CARPETA = "proveedores"
TIPOS = ["fabricante", "importador", "distribuidor mayorista", "tienda", "otro"]
CONFIG = {
    "modelo": "claude-opus-5-5",
    "esfuerzo": "medium",
    "max_busquedas": 5,
    "max_paginas": 6,
    "maximo": 6,
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
        "resumen": {"type": "string"},
    },
    "required": ["proveedores", "resumen"],
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
        "- «resumen»: dos frases sobre qué tan fácil es abastecer este pedido y qué líneas quedaron sin "
        "proveedor."
    )


def _usuario_chile() -> dict:
    return {"type": "approximate", "country": "CL", "city": "Santiago", "timezone": "America/Santiago"}


def _a_dict(bloque) -> dict:
    if isinstance(bloque, dict):
        return bloque
    return bloque.model_dump() if hasattr(bloque, "model_dump") else dict(bloque)


def _recorrer(valor, textos: list[str], urls: set[str]) -> None:
    if isinstance(valor, dict):
        for clave, v in valor.items():
            if clave == "url" and isinstance(v, str):
                urls.add(v)
            _recorrer(v, textos, urls)
    elif isinstance(valor, list):
        for v in valor:
            _recorrer(v, textos, urls)
    elif isinstance(valor, str):
        textos.append(valor)


def evidencia(bloques: list) -> tuple[str, set[str]]:
    """Texto y URLs de lo que Claude buscó y leyó (resultados de las herramientas, no su respuesta)."""
    textos: list[str] = []
    urls: set[str] = set()
    for b in bloques:
        d = _a_dict(b)
        if d.get("type") not in ("text", "thinking", "redacted_thinking"):
            _recorrer(d, textos, urls)
    return "\n".join(textos), urls


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _dominio(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def depurar(proveedores: list[dict], texto: str, urls: set[str]) -> list[dict]:
    """Deja solo los datos que se pueden respaldar con lo que se leyó en la búsqueda.

    Un correo queda si aparece escrito en una página leída; un teléfono, si sus dígitos aparecen.
    Una fuente o web que no es un link (http/https) se descarta. `verificado` = la fuente es una de las páginas
    que devolvió la búsqueda."""
    bajo = texto.lower()
    digitos = _solo_digitos(texto)
    dominios = {_dominio(u) for u in urls}
    limpios = []
    for p in proveedores:
        p = dict(p)
        avisos = []
        correo = (p.get("correo") or "").strip()
        if correo and not (_CORREO.fullmatch(correo) and correo.lower() in bajo):
            p["correo"] = None
            avisos.append("correo por confirmar")
        telefono = (p.get("telefono") or "").strip()
        if telefono and not (len(_solo_digitos(telefono)) >= 8 and _solo_digitos(telefono)[-8:] in digitos):
            p["telefono"] = None
            avisos.append("teléfono por confirmar")
        for campo in ("web", "fuente"):
            if p.get(campo) and not str(p[campo]).startswith(("https://", "http://")):
                p[campo] = None
        p["verificado"] = bool(p.get("fuente")) and (p["fuente"] in urls or _dominio(p["fuente"]) in dominios)
        if avisos:
            p["nota"] = "; ".join(x for x in (p.get("nota"), *avisos) if x)
        p["lineas"] = sorted({int(x) for x in p.get("lineas") or []})
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
    precio = cfg["precio_usd"]
    costo = (uso["entrada"] * precio["entrada_mtok"] + uso["salida"] * precio["salida_mtok"]) / 1e6 \
        + uso["busquedas"] * precio["busqueda"]
    return {
        "codigo": lic.get("codigo"),
        "fecha": (ahora or datetime.now(CHILE)).isoformat(timespec="minutes"),
        "modelo": getattr(respuesta, "model", cfg["modelo"]),
        "busquedas": uso["busquedas"], "costo_usd": round(costo, 2),
        "resumen": datos.get("resumen") or "",
        "proveedores": depurar(datos.get("proveedores") or [], texto, urls)[: cfg["maximo"]],
    }


# --- Rama `proveedores` del repositorio --------------------------------------------------------

def _cabeceras(token: str | None) -> dict:
    c = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        c["Authorization"] = f"Bearer {token}"
    return c


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


def guardar(codigo: str, datos: dict, token: str | None, repo: str = REPO, rama: str | None = None,
            timeout: float = 20) -> None:
    """Escribe `proveedores/<código>.json` en la rama (la crea la primera vez)."""
    if not token:
        raise ErrorGitHub("Falta el token de GitHub (secreto github_token).")
    rama = rama or configuracion()["rama"]
    url = f"{API_GITHUB}/repos/{repo}/contents/{CARPETA}/{codigo}.json"
    actual = requests.get(url, params={"ref": rama}, headers=_cabeceras(token), timeout=timeout)
    if actual.status_code == 404:
        existe = requests.get(f"{API_GITHUB}/repos/{repo}/branches/{rama}", headers=_cabeceras(token),
                              timeout=timeout)
        if existe.status_code == 404:
            _crear_rama(token, repo, rama, timeout)
        elif existe.status_code != 200:
            raise _error(existe)
    elif actual.status_code != 200:
        raise _error(actual)
    cuerpo = {"message": f"Proveedores para {codigo} (plataforma)", "branch": rama,
              "content": base64.b64encode(json.dumps(datos, ensure_ascii=False, indent=1).encode()).decode()}
    if actual.status_code == 200:
        cuerpo["sha"] = actual.json().get("sha")
    r = requests.put(url, json=cuerpo, headers=_cabeceras(token), timeout=timeout)
    if r.status_code not in (200, 201):
        raise _error(r)


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
    cierre = (lic.get("fecha_cierre") or "")[:10]
    cierre_txt = date.fromisoformat(cierre).strftime("%d-%m-%Y") if cierre else "próximamente"
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
