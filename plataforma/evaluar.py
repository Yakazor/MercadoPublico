"""Evaluación GO / NO GO de una licitación o Compra Ágil con tus cotizaciones, y el ranking."""
import json

import pandas as pd
import streamlit as st

import comun
from evaluar_licitaciones import REMITENTE, correos, go_no_go, informe, pct, proveedores
from radar.config import cargar_config, hoy_chile, ruta_proyecto
from radar.evaluacion import CONDICIONADO, GO, NO_GO
from radar.plataforma import es_compra_agil, evaluar_licitacion, mercado_por_item, opciones, ranking
from radar.presupuesto import IVA, armar_presupuesto

VISTAS = ["Una licitación", "Ranking"]


def pagina() -> None:
    prep = comun.datos()
    st.title("Evaluación GO / NO GO")
    st.caption("Costos, márgenes, riesgo y decisión con los supuestos de la barra lateral. Las cotizaciones que "
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

    _cotizaciones(codigo, items, mercado)
    ops = opciones(items, mercado, comun.cotizaciones().get(codigo), comun.estimar_oc(), comun.margen(), comun.otros())
    p, ev = evaluar_licitacion(lic, items, ops, comun.supuestos(), comun.margen(), comun.otros())
    _resultado(lic, p, ev, mercado)


def _cotizaciones(codigo: str, items: list[dict], mercado: list[dict]) -> None:
    """Tabla de ítems con los precios de tiendas y una columna para tus cotizaciones."""
    st.subheader("Precios por línea")
    ingresadas = st.session_state.setdefault("cotizaciones_ingresadas", {}).get(codigo, {})
    con_iva = st.toggle("Mis cotizaciones incluyen IVA", value=ingresadas.get("con_iva", False), key=f"eval_iva_{codigo}",
                        help="Las Compras Ágiles y las tiendas suelen dar el precio con IVA; se descuenta el 19 %.")
    base, editor = f"eval_base_{codigo}", f"eval_editor_{codigo}"
    if editor not in st.session_state or base not in st.session_state:
        tiendas = armar_presupuesto(items, mercado)["items"]
        st.session_state[base] = pd.DataFrame([{
            "Línea": it.get("linea"), "Producto": it.get("producto"), "Cantidad": it.get("cantidad"),
            "Unidad": it.get("unidad"), "Mejor tienda": t.get("tienda"),
            "Precio tienda (neto)": comun.pesos(t.get("costo_unitario_neto")),
            "Pagado por el Estado": comun.pesos(it.get("ref_mediana")),
            "Tu cotización (unitario)": (ingresadas.get("precios") or {}).get(str(it.get("linea"))),
        } for it, t in zip(items, tiendas)]).astype({"Tu cotización (unitario)": float})
    editado = st.data_editor(
        st.session_state[base], key=editor, hide_index=True,
        disabled=[c for c in st.session_state[base].columns if c != "Tu cotización (unitario)"],
        column_config={
            "Producto": st.column_config.TextColumn(width="medium"),
            "Cantidad": st.column_config.NumberColumn(format="%g"),
            "Precio tienda (neto)": st.column_config.NumberColumn(format="localized"),
            "Pagado por el Estado": st.column_config.NumberColumn(
                format="localized", help="Mediana del precio unitario neto en órdenes de compra parecidas"),
            "Tu cotización (unitario)": st.column_config.NumberColumn(
                min_value=0, format="localized", help="Precio por unidad que te dio el proveedor"),
        })
    precios = {str(it.get("linea")): float(v) for it, v in zip(items, editado["Tu cotización (unitario)"])
               if pd.notna(v) and v > 0}
    st.session_state["cotizaciones_ingresadas"][codigo] = {"precios": precios, "con_iva": con_iva}
    factor = 1 / (1 + IVA) if con_iva else 1
    netas = {it.get("linea"): precios[str(it.get("linea"))] * factor for it in items if str(it.get("linea")) in precios}
    if netas:
        comun.cotizaciones()[codigo] = netas
    else:
        comun.cotizaciones().pop(codigo, None)


def _resultado(lic: dict, p: dict, ev, mercado: list[dict]) -> None:
    c, m, i = ev.costos, ev.margenes, ev.ingresos
    st.subheader("Resultado")
    if p["items_sin_precio"] == len(p["items"]):
        st.info("Ninguna línea tiene precio todavía. Pide cotización a proveedores (correos abajo) e ingresa sus "
                "precios en la tabla, o activa «Estimar con OC del Estado» en los supuestos de la barra lateral.")
        _documentos(lic, p, ev, mercado, con_precios=False)
        return
    comun.aviso_decision(ev)
    k = st.columns(3) + st.columns(3)
    k[0].metric("Oferta sugerida c/IVA", comun.clp(i["oferta_total"]),
                help="Costo × (1 + otros costos) × (1 + margen) + IVA")
    k[1].metric("Monto estimado", comun.clp(i["monto_estimado"]) if i["monto_estimado"] else "—")
    k[2].metric("Margen neto", pct(m["neto_pct"]), comun.con_signo(m["neto"]))
    k[3].metric("Punto de equilibrio c/IVA", comun.clp(m["equilibrio_total"]),
                help="Oferta mínima que cubre todos los costos, directos e indirectos")
    k[4].metric("Prob. de adjudicación", f"{ev.probabilidad:.0%}", help="Estimación heurística para ordenar")
    k[5].metric("Riesgo", ev.riesgo, help="Según precios faltantes o aproximados, plazos, región, monto y registro ISP")
    if es_compra_agil(lic):
        st.caption("Compra Ágil: cotiza el total con IVA y despacho incluido.")
    sin_precio = p["items_sin_precio"]
    if sin_precio:
        st.info(f"{sin_precio} de {len(p['items'])} líneas sin precio: ingresa su cotización arriba o activa "
                "«Estimar con OC del Estado» en los supuestos.")

    a, b = st.columns(2)
    with a:
        st.markdown(
            "| Costos (netos) | Monto |\n|---|---:|\n"
            f"| Mercadería | {comun.clp(c['directos'])} |\n"
            f"| Despacho ({pct(ev.supuestos['logistica_pct'])}, zona {ev.supuestos['zona']}) | {comun.clp(c['logistica'])} |\n"
            f"| Tu trabajo ({c['horas']:g} h × {comun.clp(ev.supuestos['valor_hora'])}) | {comun.clp(c['mano_obra'])} |\n"
            f"| Garantía de fiel cumplimiento | {comun.clp(c['garantia'])} |\n"
            f"| Costo financiero (30 días) | {comun.clp(c['financiero'])} |\n"
            f"| **Costo total** | **{comun.clp(c['total'])}** |\n"
            f"| Oferta neta | {comun.clp(i['oferta_neta'])} |\n"
            f"| Margen bruto | {comun.clp(m['bruto'])} ({pct(m['bruto_pct'])}) |\n"
            f"| **Margen neto** | **{comun.clp(m['neto'])} ({pct(m['neto_pct'])})** |")
    with b:
        st.markdown(f"**Complejidad:** {ev.complejidad} · **Factibilidad:** operativa "
                    f"{ev.factibilidad['operativa'].lower()}, financiera {ev.factibilidad['financiera'].lower()}, "
                    f"plazos {ev.factibilidad['plazos'].lower()}")
        st.markdown("**Por qué**\n" + "\n".join(f"- {r}" for r in ev.razones))
        if ev.condiciones:
            st.markdown("**Condiciones para postular**\n" + "\n".join(f"- {x}" for x in ev.condiciones))
        if ev.riesgos:
            st.markdown("**Riesgos detectados**\n" + "\n".join(f"- {r}" for r in ev.riesgos))

    with st.expander("Presupuesto por línea"):
        st.dataframe(pd.DataFrame([{
            "Línea": it.get("linea"), "Producto": it.get("producto"), "Cantidad": it.get("cantidad"),
            "Costo unitario": comun.pesos(it.get("costo_unitario_neto")),
            "Oferta unitaria": comun.pesos(it.get("oferta_unitaria_neta")),
            "Subtotal oferta": comun.pesos(it.get("subtotal_oferta")), "Fuente": it.get("tienda"),
            "Coincidencia": it.get("coincidencia"), "Verificado": it.get("verificado"), "Link": it.get("url"),
        } for it in p["items"]]), hide_index=True, column_config={
            "Producto": st.column_config.TextColumn(width="large"),
            "Cantidad": st.column_config.NumberColumn(format="%g"),
            **{col: st.column_config.NumberColumn(format="localized")
               for col in ("Costo unitario", "Oferta unitaria", "Subtotal oferta")},
            "Link": st.column_config.LinkColumn(display_text="Ver")})

    _documentos(lic, p, ev, mercado)


def _documentos(lic: dict, p: dict, ev, mercado: list[dict], con_precios: bool = True) -> None:
    provs, remitente = _proveedores(lic["codigo"], mercado)
    texto_correos = correos(lic, p, provs, remitente, hoy_chile())
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
    with st.expander("Ver correos a proveedores", expanded=not con_precios):
        st.caption("Copia el texto con el botón de cada recuadro. Nunca se envían solos; revisa el correo del "
                   "proveedor en su web antes de enviar.")
        st.markdown(texto_correos.split("\n", 2)[-1].replace("\n## ", "\n#### ").removeprefix("## "))


def _proveedores(codigo: str, mercado: list[dict]) -> tuple[list[dict], dict]:
    archivo = ruta_proyecto(f"informes/mercado/{codigo}.json")
    origen = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else mercado_por_item(mercado)
    provs = proveedores(codigo, origen, ruta_proyecto("informes/evaluacion/proveedores"))
    remitente = REMITENTE | ((cargar_config().get("evaluacion") or {}).get("remitente") or {}) | dict(
        comun.secreto("remitente") or {})
    return provs, remitente


def _ranking(prep: dict) -> None:
    a, b = st.columns([1, 2])
    tipo = a.segmented_control("Mostrar", ["Todas", "Licitaciones", "Compras Ágiles"], default="Todas",
                               required=True, key="rank_tipo")
    decisiones = b.multiselect("Decisión", [GO, CONDICIONADO, NO_GO], default=[GO, CONDICIONADO], key="rank_dec")
    filas = [(l, p, e) for l, p, e in ranking(prep, comun.supuestos(), comun.margen(), comun.otros(),
                                              comun.estimar_oc(), comun.cotizaciones())
             if e.decision in decisiones and (tipo == "Todas" or es_compra_agil(l) == (tipo == "Compras Ágiles"))]
    st.caption(f"{len(filas)} evaluadas con al menos un precio, de mejor a peor (decisión y luego margen × "
               "probabilidad). Toca una fila para abrir su evaluación.")
    codigos = [l["codigo"] for l, _, _ in filas]

    def abrir():
        sel = st.session_state["rank_tabla"].selection.rows
        if sel:
            st.session_state.update(codigo=codigos[sel[0]], eval_vista=VISTAS[0])

    st.dataframe(pd.DataFrame([{
        "Código": l["codigo"], "Tipo": "Compra Ágil" if es_compra_agil(l) else l.get("tipo"), "Nombre": l.get("nombre"),
        "Decisión": e.etiqueta, "Margen neto %": (e.margenes["neto_pct"] or 0) * 100,
        "Margen neto": comun.pesos(e.margenes["neto"]), "Oferta c/IVA": comun.pesos(e.ingresos["oferta_total"]),
        "Monto estimado": comun.pesos(e.ingresos["monto_estimado"]), "Con precio": e.cobertura * 100, "Riesgo": e.riesgo,
        "Prob.": e.probabilidad * 100, "Cierre": comun.dias_texto(l.get("dias_restantes")),
    } for l, p, e in filas]), hide_index=True, key="rank_tabla", on_select=abrir, selection_mode="single-row",
        height=560, column_config={
            "Nombre": st.column_config.TextColumn(width="large"),
            **{col: st.column_config.NumberColumn(format="%.0f %%") for col in ("Margen neto %", "Con precio", "Prob.")},
            **{col: st.column_config.NumberColumn(format="localized")
               for col in ("Margen neto", "Oferta c/IVA", "Monto estimado")}})
