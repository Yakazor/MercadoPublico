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


@st.cache_data(show_spinner=False)
def _config() -> tuple[dict, dict]:
    """config.yaml una vez por proceso: `proveedores` y la firma de `evaluacion.remitente`."""
    return prov.configuracion(), (cargar_config().get("evaluacion") or {}).get("remitente") or {}


def remitente() -> dict:
    """Firma del correo: config.yaml, con lo de los secretos encima (`[remitente]`)."""
    return REMITENTE | _config()[1] | dict(comun.secreto("remitente") or {})


@st.cache_data(ttl=600, show_spinner=False)
def _guardado(codigo: str) -> dict | None:
    return prov.leer(codigo)


@st.cache_resource
def _automaticas() -> dict:
    """{fecha: búsquedas automáticas} de todas las sesiones mientras la plataforma está encendida: el tope
    diario no se reinicia al recargar la página ni al abrirla en otro equipo."""
    return {}


def _automaticas_hoy() -> int:
    return _automaticas().get(hoy_chile().isoformat(), 0)


def _sumar_automatica() -> None:
    hoy = hoy_chile().isoformat()
    cuenta = _automaticas()
    for fecha in [f for f in cuenta if f != hoy]:
        cuenta.pop(fecha, None)
    cuenta[hoy] = cuenta.get(hoy, 0) + 1


def _memoria() -> dict:
    return comun.busquedas_en_memoria()


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
    vistos = {(p.get("nombre") or "").lower() for p in encontrados}
    return encontrados + [p for p in otros if p.get("nombre") and p["nombre"].lower() not in vistos]


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
    if lic["codigo"] in ss.setdefault("prov_intentadas", set()):
        # No resultó o se interrumpió (tocar otra cosa mientras busca corta la página): no se paga de nuevo sola.
        return "La búsqueda anterior no terminó o no resultó; puedes intentarla de nuevo con el botón."
    tope = cfg.get("maximo_al_abrir_por_dia", cfg.get("maximo_al_abrir_por_sesion", 10))
    if _automaticas_hoy() >= tope:
        return f"Ya se hicieron las {tope} búsquedas automáticas de hoy (tope en `proveedores`); usa el botón."
    return None


def _buscar(lic: dict, items: list[dict], clave_api: str, cfg: dict) -> dict | None:
    import anthropic
    codigo = lic["codigo"]
    ss = st.session_state
    ss.setdefault("prov_intentadas", set()).add(codigo)
    with st.status("Buscando proveedores y precios en la web… (2 a 3 minutos). Espera a que termine antes de tocar "
                   "otra cosa.", expanded=False) as estado:
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
            estado.update(label=error, state="error")
            return None
        ss.setdefault("prov_resultados", {})[codigo] = resultado
        _memoria()[codigo] = resultado
        try:
            prov.guardar(codigo, resultado, comun.secreto("github_token"), rama=cfg["rama"])
            _guardado.clear()
            comun._indice_precios.clear()
            guardado = ""
        except (prov.ErrorGitHub, requests.RequestException) as e:   # sin guardar igual sirve en esta sesión
            guardado = f" No quedó guardada en GitHub ({e}); queda mientras tengas la plataforma abierta."
        n, m = len(resultado["proveedores"]), len(resultado.get("precios") or [])
        estado.update(label=f"Listo: {n} proveedor{'es' if n != 1 else ''} y {m} precio{'s' if m != 1 else ''} "
                      f"encontrado{'s' if n + m != 1 else ''}." + guardado, state="complete")
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


def _tabla_precios(resultado: dict, items: list[dict]) -> None:
    """Las alternativas de precio por línea, de la más barata a la más cara: la primera de cada línea
    es la que usa la evaluación (si no hay una exacta o equivalente más barata de la rutina)."""
    import pandas as pd
    precios = resultado.get("precios") or []
    if "precios" not in resultado:
        st.caption("Esta búsqueda es anterior a la de precios: «Buscar de nuevo» trae también precios.")
        return
    if not precios:
        st.caption("No se encontraron precios escritos en las páginas de los productos: pide cotización abajo.")
        return
    productos = {it.get("linea"): prov.nombre_item(it, 40) for it in items}
    cantidades = {it.get("linea"): it.get("cantidad") for it in items}
    filas, vistas = [], set()
    for m in sorted(precios, key=lambda m: (m.get("linea"), m.get("precio_unitario_neto") or 0)):
        linea = m.get("linea")
        cantidad = cantidades.get(linea)
        filas.append({
            "Línea": linea, "Producto pedido": productos.get(linea), "Mejor": linea not in vistas,
            "Proveedor": m.get("tienda"), "Producto": m.get("producto_mercado"),
            "Precio publicado": comun.pesos(m.get("precio")),
            "IVA": "incluido" if m.get("iva_incluido") else "+ IVA",
            "Costo neto unitario": comun.pesos(m.get("precio_unitario_neto")),
            "Costo neto línea": comun.pesos((m.get("precio_unitario_neto") or 0) * cantidad) if cantidad else None,
            "Coincidencia": m.get("coincidencia"), "Verificado": bool(m.get("verificado")), "Link": m.get("url"),
            "Nota": m.get("nota")})
        vistas.add(linea)
    lineas = len({f["Línea"] for f in filas})
    st.markdown(f"##### Precios encontrados · {len(filas)} alternativas para {lineas} de {len(items)} líneas")
    st.caption("De la más barata a la más cara por línea. La evaluación (GO / NO GO) usa la más barata exacta o "
               "equivalente; una aproximada solo si no hay otra. Verificado = Claude abrió la página del producto y "
               "el precio está escrito ahí; los demás salieron en los resultados de búsqueda. Confírmalo con el "
               "proveedor antes de ofertar.")
    st.dataframe(pd.DataFrame(filas), hide_index=True, placeholder="—", column_config={
        "Línea": st.column_config.NumberColumn(width=50),
        "Producto pedido": st.column_config.TextColumn(width=150),
        "Mejor": st.column_config.CheckboxColumn(width=55, help="La más barata de esa línea"),
        "Proveedor": st.column_config.TextColumn(width=120),
        "Producto": st.column_config.TextColumn(width=180),
        "Precio publicado": st.column_config.NumberColumn(format="localized", width=95),
        "IVA": st.column_config.TextColumn(width=70),
        "Costo neto unitario": st.column_config.NumberColumn(format="localized", width=95,
                                                             help="Sin IVA y por unidad pedida"),
        "Costo neto línea": st.column_config.NumberColumn(format="localized", width=100,
                                                          help="Costo neto unitario × cantidad pedida"),
        "Coincidencia": st.column_config.TextColumn(width=95, help="exacta = el mismo producto; equivalente = "
                                                    "cumple lo pedido, otra marca; aproximada = le falta algo"),
        "Verificado": st.column_config.CheckboxColumn(width=80, help="El precio está escrito en la página del "
                                                      "producto que Claude abrió"),
        "Link": st.column_config.LinkColumn(display_text="Ver", width=50),
        "Nota": st.column_config.TextColumn(width=180)})


def seccion(lic: dict, items: list[dict], mercado: list[dict]) -> None:
    """Proveedores (busca solo al abrir) y la solicitud de cotización, al final de la ficha."""
    codigo = lic["codigo"]
    cfg = _config()[0]
    clave_api = comun.secreto("anthropic_api_key")
    st.markdown("#### Proveedores")
    if not items:
        st.caption("Sin ítems en el radar: revisa la ficha en Mercado Público para saber qué cotizar.")
        return
    resultado = busqueda(codigo)
    if resultado is None and clave_api:
        motivo = _motivo_sin_auto(lic, cfg)
        if motivo is None:
            _sumar_automatica()
            resultado = _buscar(lic, items, clave_api, cfg)
        else:
            st.caption(motivo)
            if st.button("Buscar proveedores", icon="🔎", key=f"prov_buscar_{codigo}",
                         help="Claude busca en la web a quién comprarle y a qué precio (unos US$0,40–0,80 por búsqueda)."):
                resultado = _buscar(lic, items, clave_api, cfg)
        if resultado and resultado.get("precios"):
            st.rerun()      # la evaluación de arriba se vuelve a calcular con los precios encontrados
    if resultado:
        st.caption(comun.md(
            f"Búsqueda del {comun.fecha_hora(resultado.get('fecha'))} · {resultado.get('busquedas', 0)} búsquedas "
            f"web · costo aprox. US$ {resultado.get('costo_usd', 0):.2f}. Los correos y teléfonos son los que "
            "aparecen en sus páginas; lo que no se encontró va «por confirmar». Los precios encontrados ya cuentan en "
            "la evaluación de esta licitación."))
        if resultado.get("resumen"):
            st.markdown(comun.md(resultado["resumen"]))
        _tabla(resultado, items)
        _tabla_precios(resultado, items)
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
    firma = remitente()
    correo = prov.solicitud(lic, items, elegido, firma, hoy_chile(), lineas)
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
    if any(str(v).startswith("[") for v in firma.values()):
        avisos.append("Tu firma está incompleta: agrega `[remitente]` (empresa, nombre, cargo, contacto) en los "
                      "secretos de la plataforma.")
    st.caption(" ".join(avisos))
