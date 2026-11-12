"""Evaluación GO / NO GO de una licitación o Compra Ágil con tus cotizaciones, y el ranking."""
import pandas as pd
import streamlit as st

import comun
import cotizar
from evaluar_licitaciones import correos, go_no_go, informe, pct
from radar.config import hoy_chile
from radar.evaluacion import CONDICIONADO, FALTA_PRECIO, GO, NO_GO
from radar.plataforma import es_compra_agil, evaluar_licitacion, opciones, ranking
from radar.presupuesto import IVA, armar_presupuesto, referencia_confiable

VISTAS = ["Una licitación", "Ranking"]


def pagina() -> None:
    prep = comun.datos()
    st.title("Evaluación GO / NO GO")
    st.caption("Costos, márgenes, riesgo y decisión con tus supuestos (⚙️ Supuestos, arriba). Las cotizaciones que "
               "ingreses mandan sobre los precios de tiendas y quedan mientras tengas la plataforma abierta.")
    if st.segmented_control("Vista", VISTAS, default=VISTAS[0], required=True, key="eval_vista",
                            label_visibility="collapsed") == VISTAS[1]:
        _ranking(prep)
    else:
        _una(prep)


def _etiqueta(lic: dict, prep: dict) -> str:
    marca = "⚡ " if es_compra_agil(lic) else ""
    precios = " · con precios" if lic["codigo"] in prep["mercado"] else ""
    return f"{marca}{lic['codigo']} · {(lic.get('nombre') or '')[:70]}{precios}"


def _una(prep: dict) -> None:
    lics = {l["codigo"]: l for l in prep["licitaciones"]}
    if not lics:
        st.info("No hay licitaciones abiertas en los datos.")
        return
    # Con precios primero; dentro de cada grupo, las que cierran antes.
    codigos = sorted(lics, key=lambda c: (c not in prep["mercado"], lics[c].get("fecha_cierre") or "9999"))
    if st.session_state.get("codigo") in lics:
        st.session_state["eval_codigo"] = st.session_state["codigo"]
    elif st.session_state.get("eval_codigo") not in lics:
        st.session_state["eval_codigo"] = codigos[0]
    codigo = st.selectbox("Licitación o Compra Ágil", codigos, key="eval_codigo",
                          format_func=lambda c: _etiqueta(lics[c], prep),
                          on_change=lambda: st.session_state.update(codigo=st.session_state["eval_codigo"]))
    lic, items, mercado = lics[codigo], prep["items"].get(codigo, []), prep["mercado"].get(codigo, [])
    st.caption(" · ".join(x for x in (lic.get("organismo"), lic.get("region"),
                                      f"cierra {comun.fecha_hora(lic.get('fecha_cierre'))} "
                                      f"({comun.dias_texto(lic.get('dias_restantes'))})") if x))
    if not items:
        st.info("El radar no trae los ítems de esta licitación, así que no se puede evaluar. Revisa la ficha.")
        st.link_button("Abrir en Mercado Público", lic.get("url") or "", icon="🔗")
        return

    _cotizaciones(codigo, items, mercado, es_compra_agil(lic))
    ops = opciones(items, mercado, comun.cotizaciones().get(codigo), comun.estimar_oc(), comun.margen(), comun.otros(),
                   not comun.supuestos()["recupera_iva_compras"])
    p, ev = evaluar_licitacion(lic, items, ops, comun.supuestos(), comun.margen(), comun.otros())
    _resultado(lic, items, p, ev, mercado)


def _cotizaciones(codigo: str, items: list[dict], mercado: list[dict], compra_agil: bool) -> None:
    """Tabla de ítems con los precios de tiendas y una columna para tus cotizaciones."""
    st.subheader("Precios por línea")
    ingresadas = st.session_state.setdefault("cotizaciones_ingresadas", {}).get(codigo, {})
    con_iva = st.toggle("Mis cotizaciones incluyen IVA", value=ingresadas.get("con_iva", False), key=f"eval_iva_{codigo}",
                        help="Las Compras Ágiles y las tiendas suelen dar el precio con IVA; se descuenta el 19 %.")
    base, editor, firma = f"eval_base_{codigo}", f"eval_editor_{codigo}", f"eval_firma_{codigo}"
    tiendas = armar_presupuesto(items, mercado)["items"]
    # La tabla se arma de nuevo si cambian los ítems o los precios de tiendas (datos recargados);
    # tus cotizaciones se conservan porque se guardan por línea en «cotizaciones_ingresadas».
    actual = tuple((it.get("linea"), it.get("cantidad"), t.get("tienda"), t.get("costo_unitario_neto"))
                   for it, t in zip(items, tiendas))
    if editor not in st.session_state or base not in st.session_state or st.session_state.get(firma) != actual:
        st.session_state.pop(editor, None)
        st.session_state[firma] = actual
        st.session_state[base] = pd.DataFrame([{
            "Línea": it.get("linea"), "Producto": it.get("producto"), "Cantidad": it.get("cantidad"),
            "Unidad": it.get("unidad"), "Mejor tienda": t.get("tienda") or "—",
            "Precio tienda (neto)": comun.pesos(t.get("costo_unitario_neto")),
            "Pagado por el Estado": comun.pesos(it.get("ref_mediana")),
            "Ref. OC": None if not it.get("ref_mediana") else ("precisa" if referencia_confiable(it)
                                                               else "categoría amplia"),
            "Tu cotización (unitario)": (ingresadas.get("precios") or {}).get(str(it.get("linea"))),
        } for it, t in zip(items, tiendas)]).astype({"Tu cotización (unitario)": float})
    editado = st.data_editor(
        st.session_state[base], key=editor, hide_index=True,
        disabled=[c for c in st.session_state[base].columns if c != "Tu cotización (unitario)"],
        column_config={
            "Línea": st.column_config.NumberColumn(width=50),
            "Producto": st.column_config.TextColumn(width=200),
            "Cantidad": st.column_config.NumberColumn(format="%g", width=75),
            "Unidad": st.column_config.TextColumn(width=65),
            "Mejor tienda": st.column_config.TextColumn(width=120),
            "Precio tienda (neto)": st.column_config.NumberColumn(format="localized", width=110),
            "Pagado por el Estado": st.column_config.NumberColumn(
                format="localized", width=125, help="Mediana del precio unitario neto en órdenes de compra del mismo "
                                                    "producto ONU (una categoría: puede mezclar modelos muy distintos)"),
            "Ref. OC": st.column_config.TextColumn(
                width=110, help="precisa = 5 o más órdenes y precios parecidos entre sí (sirve para comparar); "
                                "categoría amplia = pocas órdenes o productos muy distintos (p. ej. todos los "
                                "notebooks): no compares el precio de tienda con ella"),
            "Tu cotización (unitario)": st.column_config.NumberColumn(
                min_value=0, format="localized", width=130, help="Precio por unidad que te dio el proveedor"),
        }, placeholder="—")
    if not mercado:
        comun.pedir_precios(codigo, compra_agil)
    precios = {str(int(linea)): float(v) for linea, v in zip(editado["Línea"], editado["Tu cotización (unitario)"])
               if pd.notna(v) and v > 0}
    st.session_state["cotizaciones_ingresadas"][codigo] = {"precios": precios, "con_iva": con_iva}
    factor = 1 / (1 + IVA) if con_iva else 1
    netas = {it.get("linea"): precios[str(it.get("linea"))] * factor for it in items if str(it.get("linea")) in precios}
    if netas:
        comun.cotizaciones()[codigo] = netas
    else:
        comun.cotizaciones().pop(codigo, None)


def _resultado(lic: dict, items: list[dict], p: dict, ev, mercado: list[dict]) -> None:
    c, m, i = ev.costos, ev.margenes, ev.ingresos
    st.subheader("Resultado")
    if p["items_sin_precio"] == len(p["items"]):
        st.info("Ninguna línea tiene precio todavía. Pide cotización a un proveedor (solicitud abajo) e ingresa sus "
                "precios en la tabla, pide a Claude precios de tiendas (texto de arriba) o activa «Estimar con OC del Estado» "
                "en ⚙️ Supuestos.")
        _documentos(lic, items, p, ev, mercado, con_precios=False)
        return
    comun.aviso_decision(ev)
    n, sin_precio = len(p["items"]), p["items_sin_precio"]
    # Con líneas sin precio, la oferta, el margen y el equilibrio salen de una parte del pedido: se dice en
    # la misma cifra, no solo en un aviso.
    parcial = f" · parcial ({n - sin_precio} de {n} líneas)" if sin_precio else ""
    ayuda_parcial = (f" Solo incluye las {n - sin_precio} líneas con precio: con las otras {sin_precio} será mayor."
                     if sin_precio else "")
    k = st.columns(3) + st.columns(3)
    k[0].metric("Oferta sugerida c/IVA" + parcial, comun.clp(i["oferta_total"]),
                help="Costo × (1 + otros costos) × (1 + margen) + IVA." + ayuda_parcial)
    k[1].metric("Monto estimado", comun.clp(i["monto_estimado"]) if i["monto_estimado"] else "—")
    k[2].metric("Margen neto" + parcial, pct(m["neto_pct"]), comun.con_signo(m["neto"]),
                help="Margen sobre la oferta neta, después de todos los costos." + ayuda_parcial)
    k[3].metric("Punto de equilibrio c/IVA" + parcial, comun.clp(m["equilibrio_total"]),
                help="Oferta mínima que cubre todos los costos, directos e indirectos." + ayuda_parcial)
    sin_decision = ev.decision == FALTA_PRECIO
    k[4].metric("Prob. de adjudicación", "—" if sin_decision else f"{ev.probabilidad:.0%}",
                help="Sin decisión todavía: faltan precios." if sin_decision else "Estimación heurística para ordenar")
    k[5].metric("Riesgo", ev.riesgo, help="Según precios faltantes o aproximados, plazos, región, monto y registro ISP")
    if es_compra_agil(lic):
        st.caption("Compra Ágil: cotiza el total con IVA y despacho incluido.")
    if sin_precio:
        st.info(f"{sin_precio} de {n} líneas sin precio: las cifras de arriba son parciales. Ingresa su cotización "
                "arriba o activa «Estimar con OC del Estado» en ⚙️ Supuestos.")
    monto, oferta = i["monto_estimado"], i["oferta_total"]
    if monto and oferta > monto:
        st.warning(f"La oferta sugerida ({comun.clp(oferta)}) supera el monto estimado ({comun.clp(monto)}) en "
                   f"{oferta / monto - 1:.0%}: casi nunca se adjudica sobre el presupuesto. Baja el margen en "
                   "⚙️ Supuestos o consigue precio de distribuidor.")
    if oferta < m["equilibrio_total"]:
        st.warning(f"La oferta sugerida ({comun.clp(oferta)}) queda bajo el punto de equilibrio "
                   f"({comun.clp(m['equilibrio_total'])}): con este margen perderías plata. Sube el margen en "
                   "⚙️ Supuestos.")

    a, b = st.columns(2)
    with a:
        st.markdown(comun.md(
            "| Costos (netos) | Monto |\n|---|---:|\n"
            f"| Mercadería | {comun.clp(c['directos'])} |\n"
            + (f"| IVA de las compras (sin crédito fiscal) | {comun.clp(c['iva_compras'])} |\n" if c.get("iva_compras") else "")
            + f"| Despacho ({pct(ev.supuestos['logistica_pct'])}, zona {ev.supuestos['zona']}) | {comun.clp(c['logistica'])} |\n"
            f"| Tu trabajo ({c['horas']:g} h × {comun.clp(ev.supuestos['valor_hora'])}) | {comun.clp(c['mano_obra'])} |\n"
            f"| Garantía de fiel cumplimiento | {comun.clp(c['garantia'])} |\n"
            f"| Costo financiero (30 días) | {comun.clp(c['financiero'])} |\n"
            f"| **Costo total** | **{comun.clp(c['total'])}** |\n"
            f"| Oferta neta | {comun.clp(i['oferta_neta'])} |\n"
            f"| Margen bruto | {comun.clp(m['bruto'])} ({pct(m['bruto_pct'])}) |\n"
            f"| **Margen neto** | **{comun.clp(m['neto'])} ({pct(m['neto_pct'])})** |"))
    with b:
        st.markdown(f"**Complejidad:** {ev.complejidad} · **Factibilidad:** operativa "
                    f"{ev.factibilidad['operativa'].lower()}, financiera {ev.factibilidad['financiera'].lower()}, "
                    f"plazos {ev.factibilidad['plazos'].lower()}")
        st.markdown(comun.md("**Por qué**\n" + "\n".join(f"- {r}" for r in ev.razones)))
        if ev.condiciones:
            st.markdown(comun.md("**Condiciones para postular**\n" + "\n".join(f"- {x}" for x in ev.condiciones)))
        if ev.riesgos:
            st.markdown(comun.md("**Riesgos detectados**\n" + "\n".join(f"- {r}" for r in ev.riesgos)))

    with st.expander("Presupuesto por línea"):
        st.dataframe(pd.DataFrame([{
            "Línea": it.get("linea"), "Producto": it.get("producto"), "Cantidad": it.get("cantidad"),
            "Costo unitario": comun.pesos(it.get("costo_unitario_neto")),
            "Oferta unitaria": comun.pesos(it.get("oferta_unitaria_neta")),
            "Subtotal oferta": comun.pesos(it.get("subtotal_oferta")), "Fuente": it.get("tienda"),
            "Tipo de precio": " · ".join(x for x in (it.get("coincidencia"), "verificado" if it.get("verificado") else "")
                                         if x) or None,
            "Link": it.get("url"),
        } for it in p["items"]]), hide_index=True, column_config={
            "Línea": st.column_config.NumberColumn(width=50),
            "Producto": st.column_config.TextColumn(width=160),
            "Cantidad": st.column_config.NumberColumn(format="%g", width=70),
            "Costo unitario": st.column_config.NumberColumn(format="localized", width=95),
            "Oferta unitaria": st.column_config.NumberColumn(format="localized", width=95),
            "Subtotal oferta": st.column_config.NumberColumn(format="localized", width=110),
            "Fuente": st.column_config.TextColumn(width=100),
            "Tipo de precio": st.column_config.TextColumn(
                width=130, help="exacta / equivalente / aproximada / estimada (OC), y si se verificó en la tienda"),
            "Link": st.column_config.LinkColumn(display_text="Ver", width=50)}, placeholder="—")

    _documentos(lic, items, p, ev, mercado)


def _documentos(lic: dict, items: list[dict], p: dict, ev, mercado: list[dict], con_precios: bool = True) -> None:
    provs = cotizar.lista(lic["codigo"], mercado)
    texto_correos = correos(lic, p, provs, cotizar.remitente(), hoy_chile())
    st.subheader("Documentos")
    d = st.columns(4)
    if con_precios:
        d[0].download_button("Ficha GO / NO GO", go_no_go(lic, ev), f"{lic['codigo']}_go_no_go.md", "text/markdown",
                             icon="📄", width="stretch")
        d[1].download_button("Informe ejecutivo", informe(lic, p, ev, provs, comun.supuestos()),
                             f"{lic['codigo']}_informe.md", "text/markdown", icon="📄", width="stretch")
    d[2].download_button("Correos a proveedores", texto_correos, f"{lic['codigo']}_correos.md", "text/markdown",
                         icon="✉️", width="stretch")
    if d[3].button("Orden de compra", icon="🧾", type="primary", width="stretch",
                   help="Arma la orden al proveedor con estos ítems y costos"):
        comun.ir_a("orden", lic["codigo"])
    cotizar.panel_chrome(lic, items)      # precios sin gastar de la API; al guardar, la evaluación se recalcula
    with st.expander("Solicitud de cotización a un proveedor", expanded=not con_precios):
        cotizar.panel_correo(lic, items, provs)


def _ranking(prep: dict) -> None:
    a, b, c = st.columns([1.2, 1.6, 1.6])
    tipo = a.segmented_control("Mostrar", ["Todas", "Licitaciones", "Compras Ágiles"], default="Todas",
                               required=True, key="rank_tipo")
    decisiones = b.multiselect("Decisión", [GO, CONDICIONADO, FALTA_PRECIO, NO_GO], default=[GO, CONDICIONADO], key="rank_dec",
                               format_func=comun.DECISION_CORTA.get, placeholder="Todas")
    decisiones = decisiones or [GO, CONDICIONADO, FALTA_PRECIO, NO_GO]      # vacío = todas, como los otros filtros
    cv_txt = c.segmented_control("Compra y venta directa", ["Todas", *comun.COMPRA_VENTA.values()], default="Todas",
                                 required=True, key="rank_cv", help=comun.AYUDA_COMPRA_VENTA)
    cv = comun.compra_venta_por_codigo()
    estado = next((k for k, v in comun.COMPRA_VENTA.items() if v == cv_txt), "todas")
    evaluadas = ranking(prep, comun.supuestos(), comun.margen(), comun.otros(), comun.estimar_oc(), comun.cotizaciones())
    filas = [(l, p, e) for l, p, e in evaluadas
             if e.decision in decisiones and (tipo == "Todas" or es_compra_agil(l) == (tipo == "Compras Ágiles"))
             and (estado == "todas" or cv.get(l["codigo"], (None, ""))[0] is estado)]
    st.caption(f"{comun.evaluadas_texto(len(filas), len(evaluadas))}, de mejor a peor (decisión y luego margen × "
               "probabilidad). ⚡ = Compra Ágil. Marca la casilla a la izquierda de una fila para abrir su evaluación.")
    if not filas:
        st.info("Ninguna evaluada con estos filtros. Agrega decisiones en «Decisión» (por ejemplo ⚪ Falta precio) "
                "o elige «Todas».")
        return
    codigos = [l["codigo"] for l, _, _ in filas]

    def abrir():
        sel = st.session_state["rank_tabla"].selection.rows
        if sel and sel[0] < len(codigos):
            st.session_state.update(codigo=codigos[sel[0]], eval_vista=VISTAS[0])

    st.dataframe(pd.DataFrame([{
        "Código": l["codigo"], "Nombre": ("⚡ " if es_compra_agil(l) else "") + (l.get("nombre") or ""),
        "Decisión": comun.DECISION_CORTA[e.decision],
        "Compra-venta": comun.COMPRA_VENTA[cv.get(l["codigo"], (None, ""))[0]],
        "Margen neto": (e.margenes["neto_pct"] or 0) * 100,
        "Oferta c/IVA": comun.pesos(e.ingresos["oferta_total"]),
        "Monto estimado": comun.pesos(e.ingresos["monto_estimado"]), "Cierre": comun.dias_texto(l.get("dias_restantes")),
    } for l, p, e in filas]), hide_index=True, key="rank_tabla", on_select=abrir, selection_mode="single-row",
        height=560, column_config={
            "Código": st.column_config.TextColumn(width=130),
            "Nombre": st.column_config.TextColumn(width=260),
            "Decisión": st.column_config.TextColumn(width=140),
            "Compra-venta": st.column_config.TextColumn(width=105, help=comun.AYUDA_COMPRA_VENTA),
            "Margen neto": st.column_config.NumberColumn(format="%.0f %%", width=85),
            "Oferta c/IVA": st.column_config.NumberColumn(format="localized", width=105),
            "Monto estimado": st.column_config.NumberColumn(format="localized", width=105),
            "Cierre": st.column_config.TextColumn(width=70)}, placeholder="—")
