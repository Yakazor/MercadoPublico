"""Proveedores y solicitud de cotización: la sección que cierra la ficha y la Evaluación.

Al abrir una licitación o Compra Ágil, Claude busca en la web a quién comprarle (si están el
secreto `anthropic_api_key` y `proveedores.buscar_al_abrir`), y la búsqueda queda guardada en la
rama `proveedores` para no repetirla. Abajo, el correo para pedir la cotización formal al
proveedor elegido, listo para abrir en Gmail o en el programa de correo: nunca se envía solo.
"""
import json

import requests
import streamlit as st

import comun
from evaluar_licitaciones import REMITENTE, proveedores as proveedores_rutina
from radar import proveedores as prov
from radar.config import cargar_config, hoy_chile, ruta_proyecto
from radar.plataforma import es_compra_agil, mercado_por_item, solo_emt, soy_emt

LARGO_GMAIL = 7000   # sobre esto el enlace a Gmail puede no abrir: mejor copiar el texto


def remitente() -> dict:
    """Firma del correo: config.yaml, con lo de los secretos encima (`[remitente]`)."""
    return REMITENTE | ((cargar_config().get("evaluacion") or {}).get("remitente") or {}) | dict(
        comun.secreto("remitente") or {})


@st.cache_data(ttl=600, show_spinner=False)
def _guardado(codigo: str) -> dict | None:
    return prov.leer(codigo)


@st.cache_resource
def _memoria() -> dict:
    """Búsquedas hechas mientras la plataforma está encendida, para todas las sesiones: si GitHub no
    las pudo guardar (token sin permiso), otra sesión no vuelve a pagarlas."""
    return {}


def busqueda(codigo: str) -> dict | None:
    """La búsqueda de esta sesión, la de otra sesión o la guardada en la rama `proveedores`."""
    return (st.session_state.setdefault("prov_resultados", {}).get(codigo) or _memoria().get(codigo)
            or _guardado(codigo))


def lista(codigo: str, mercado: list[dict]) -> list[dict]:
    """Proveedores para el correo: los de la búsqueda y, sin repetir, los de la rutina diaria o
    las tiendas con precio de esta licitación."""
    encontrados = list((busqueda(codigo) or {}).get("proveedores") or [])
    archivo = ruta_proyecto(f"informes/mercado/{codigo}.json")
    origen = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else mercado_por_item(mercado)
    otros = proveedores_rutina(codigo, origen,
                               ruta_proyecto("informes/evaluacion/proveedores"))
    vistos = {p.get("nombre", "").lower() for p in encontrados}
    return encontrados + [p for p in otros if p.get("nombre", "").lower() not in vistos]


def _motivo_sin_auto(lic: dict, cfg: dict) -> str | None:
    """Por qué no se busca solo al abrir (None = se busca)."""
    ss = st.session_state
    if not cfg.get("buscar_al_abrir"):
        return "La búsqueda automática está apagada (`proveedores.buscar_al_abrir`)."
    if es_compra_agil(lic) and solo_emt(lic) and not soy_emt():
        return "Es de 1er llamado y no puedes cotizarla, así que no se buscó sola."
    estado, _ = comun.compra_venta_por_codigo().get(lic["codigo"], (None, ""))
    if estado is False:
        return "Incluye servicios o registro ISP (no es compra y venta directa), así que no se buscó sola."
    if lic["codigo"] in ss.setdefault("prov_fallidas", set()):
        return "La búsqueda anterior no resultó."
    if ss.get("prov_automaticas", 0) >= cfg.get("maximo_al_abrir_por_sesion", 10):
        return "Ya se hicieron las búsquedas automáticas de esta sesión (tope en `proveedores`)."
    return None


def _buscar(lic: dict, items: list[dict], clave_api: str, cfg: dict) -> dict | None:
    import anthropic
    codigo = lic["codigo"]
    ss = st.session_state
    with st.status("Buscando proveedores en la web… (1 a 2 minutos)", expanded=False) as estado:
        try:
            resultado = prov.buscar(lic, items, clave_api, cfg)
        except prov.ErrorBusqueda as e:
            error = str(e)
        except anthropic.AuthenticationError:
            error = "La clave de la API de Claude (secreto anthropic_api_key) no es válida."
        except anthropic.PermissionDeniedError:
            error = "La clave de la API de Claude no tiene permiso para buscar en la web."
        except anthropic.RateLimitError:
            error = "La API de Claude pidió esperar un poco (límite de uso). Intenta en unos minutos."
        except anthropic.APIStatusError as e:
            error = f"La API de Claude respondió con un error ({e.status_code}). Intenta de nuevo."
        except anthropic.APIConnectionError:
            error = "No hubo conexión con la API de Claude. Intenta de nuevo."
        else:
            error = None
        if error:
            ss.setdefault("prov_fallidas", set()).add(codigo)
            estado.update(label=error, state="error")
            return None
        ss.setdefault("prov_resultados", {})[codigo] = resultado
        _memoria()[codigo] = resultado
        ss.get("prov_fallidas", set()).discard(codigo)
        try:
            prov.guardar(codigo, resultado, comun.secreto("github_token"), rama=cfg["rama"])
            _guardado.clear()
            guardado = ""
        except (prov.ErrorGitHub, requests.RequestException) as e:   # sin guardar igual sirve en esta sesión
            guardado = f" No quedó guardada en GitHub ({e}); queda mientras tengas la plataforma abierta."
        n = len(resultado["proveedores"])
        estado.update(label=f"Listo: {n} proveedor{'es' if n != 1 else ''} encontrado{'s' if n != 1 else ''}."
                      + guardado, state="complete")
    return resultado


def _tabla(resultado: dict, items: list[dict]) -> None:
    import pandas as pd
    productos = {it.get("linea"): prov.nombre_item(it, 40) for it in items}
    filas = [{
        "Proveedor": p.get("nombre"), "Tipo": p.get("tipo"),
        "Líneas": ", ".join(str(x) for x in p.get("lineas") or []) or None,
        "Qué vende": p.get("productos"), "Ciudad": p.get("ciudad"), "Correo": p.get("correo"),
        "Teléfono": p.get("telefono"), "Web": p.get("web"), "Fuente": p.get("fuente"),
        "Verificado": bool(p.get("verificado")), "Nota": p.get("nota"),
    } for p in resultado.get("proveedores") or []]
    if not filas:
        st.caption("La búsqueda no encontró proveedores para estos productos.")
        return
    st.dataframe(pd.DataFrame(filas), hide_index=True, placeholder="—", column_config={
        "Proveedor": st.column_config.TextColumn(width=150),
        "Tipo": st.column_config.TextColumn(width=110),
        "Líneas": st.column_config.TextColumn(width=70, help="Líneas del pedido que vende: "
                                              + "; ".join(f"{k} = {v}" for k, v in list(productos.items())[:12])),
        "Qué vende": st.column_config.TextColumn(width=200),
        "Ciudad": st.column_config.TextColumn(width=90),
        "Correo": st.column_config.TextColumn(width=160),
        "Teléfono": st.column_config.TextColumn(width=110),
        "Web": st.column_config.LinkColumn(display_text="Abrir", width=60),
        "Fuente": st.column_config.LinkColumn(display_text="Ver", width=50, help="Página donde se encontró"),
        "Verificado": st.column_config.CheckboxColumn(width=80, help="La fuente es una de las páginas que "
                                                      "devolvió la búsqueda"),
        "Nota": st.column_config.TextColumn(width=200)})


def seccion(lic: dict, items: list[dict], mercado: list[dict]) -> None:
    """Proveedores (busca solo al abrir) y la solicitud de cotización, al final de la ficha."""
    codigo = lic["codigo"]
    cfg = prov.configuracion()
    clave_api = comun.secreto("anthropic_api_key")
    st.markdown("#### Proveedores")
    if not items:
        st.caption("Sin ítems en el radar: revisa la ficha en Mercado Público para saber qué cotizar.")
        return
    resultado = busqueda(codigo)
    if resultado is None and clave_api:
        motivo = _motivo_sin_auto(lic, cfg)
        if motivo is None:
            st.session_state["prov_automaticas"] = st.session_state.get("prov_automaticas", 0) + 1
            resultado = _buscar(lic, items, clave_api, cfg)
        else:
            st.caption(motivo)
            if st.button("Buscar proveedores", icon="🔎", key=f"prov_buscar_{codigo}",
                         help="Claude busca en la web a quién comprarle (unos US$0,20–0,40 por búsqueda)."):
                resultado = _buscar(lic, items, clave_api, cfg)
    if resultado:
        st.caption(comun.md(
            f"Búsqueda del {comun.fecha_hora(resultado.get('fecha'))} · {resultado.get('busquedas', 0)} búsquedas "
            f"web · costo aprox. US$ {resultado.get('costo_usd', 0):.2f}. Los correos y teléfonos son los que "
            "aparecen en sus páginas; lo que no se encontró va «por confirmar»."))
        if resultado.get("resumen"):
            st.markdown(comun.md(resultado["resumen"]))
        _tabla(resultado, items)
        if clave_api and st.button("Buscar de nuevo", icon="🔄", key=f"prov_otra_{codigo}",
                                   help="Otra búsqueda (tiene costo); reemplaza la guardada"):
            st.session_state.setdefault("prov_resultados", {}).pop(codigo, None)
            _memoria().pop(codigo, None)
            nuevo = _buscar(lic, items, clave_api, cfg)
            if nuevo:
                st.rerun()
    elif not clave_api:
        st.info("Para que Claude busque proveedores al abrir cada licitación, agrega el secreto "
                "`anthropic_api_key` (tu clave de la API de Claude, de console.anthropic.com) en los secretos de "
                "la plataforma. Mientras tanto se muestran los proveedores de la rutina diaria o las tiendas "
                "con precio, si hay.")
    panel_correo(lic, items, lista(codigo, mercado))


def panel_correo(lic: dict, items: list[dict], proveedores: list[dict]) -> None:
    """El correo para pedir la cotización formal al proveedor elegido."""
    codigo = lic["codigo"]
    st.markdown("#### Solicitud de cotización")
    opciones = proveedores or [{"nombre": "[Proveedor]", "lineas": []}]
    productos = {it.get("linea"): prov.nombre_item(it, 60) for it in items}

    def etiqueta(i: int) -> str:
        p = opciones[i]
        cubre = f" · líneas {', '.join(str(x) for x in p['lineas'])}" if p.get("lineas") else ""
        return f"{p.get('nombre')}{cubre}" + ("" if p.get("correo") else " · sin correo")

    a, b = st.columns([1, 2])
    i = a.selectbox("Proveedor", range(len(opciones)), format_func=etiqueta, key=f"cot_prov_{codigo}")
    elegido = opciones[i]
    todas = list(productos)
    defecto = [x for x in elegido.get("lineas") or [] if x in productos] or todas
    lineas = b.multiselect("Líneas a cotizar", todas, default=defecto, key=f"cot_lineas_{codigo}_{i}",
                           format_func=lambda x: f"{x} · {productos[x][:40]}")
    correo = prov.solicitud(lic, items, elegido, remitente(), hoy_chile(), lineas)
    correo["para"] = st.text_input("Para", correo["para"], key=f"cot_para_{codigo}_{i}",
                                   placeholder="correo del proveedor (búscalo en su web si no aparece)")
    st.text_input("Asunto", correo["asunto"], disabled=True, key=f"cot_asunto_{codigo}_{i}")
    st.code(correo["cuerpo"], language=None, wrap_lines=True)
    c = st.columns(3)
    gmail = prov.enlace_gmail(correo)
    c[0].link_button("Abrir en Gmail", gmail, icon="✉️", type="primary", width="stretch",
                     disabled=len(gmail) > LARGO_GMAIL)
    c[1].link_button("Abrir en mi correo", prov.enlace_correo(correo), icon="📧", width="stretch",
                     disabled=len(gmail) > LARGO_GMAIL)
    c[2].download_button("Descargar texto", f"Para: {correo['para']}\nAsunto: {correo['asunto']}\n\n{correo['cuerpo']}",
                         f"{codigo}_cotizacion_{i + 1}.txt", "text/plain", icon="📥", width="stretch",
                         key=f"cot_txt_{codigo}_{i}")
    avisos = ["Nada se envía solo: el correo se abre listo para que lo revises y lo envíes tú."]
    if len(gmail) > LARGO_GMAIL:
        avisos.append("Es muy largo para abrirlo con un enlace: copia el texto (botón del recuadro) o descárgalo.")
    if any(str(v).startswith("[") for v in remitente().values()):
        avisos.append("Tu firma está incompleta: agrega `[remitente]` (empresa, nombre, cargo, contacto) en los "
                      "secretos de la plataforma.")
    st.caption(" ".join(avisos))
