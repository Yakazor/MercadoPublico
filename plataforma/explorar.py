"""Licitaciones y Compras Ágiles abiertas: filtros, tabla y ficha con sus ítems."""
import re

import pandas as pd
import streamlit as st

import comun
from radar.plataforma import es_compra_agil, filtrar


def licitaciones() -> None:
    _explorar(compra_agil=False)


def compras_agiles() -> None:
    _explorar(compra_agil=True)


def _explorar(compra_agil: bool) -> None:
    prep = comun.datos()
    pre = "ca" if compra_agil else "lic"
    todas = [l for l in prep["licitaciones"] if es_compra_agil(l) == compra_agil]
    if compra_agil:
        st.title("Compras Ágiles")
        st.caption("Hasta 100 UTM: se cotiza el total con IVA y despacho. En el primer llamado solo pueden "
                   "cotizar empresas de menor tamaño; el plazo de entrega lo fija el comprador.")
    else:
        st.title("Licitaciones")
        st.caption("Licitaciones abiertas de tus rubros. Las bases y anexos están en la ficha de Mercado Público "
                   "(la API no los entrega).")

    texto = st.text_input("Buscar", placeholder="código, nombre, organismo o producto", key=f"{pre}_texto")
    with st.expander("Más filtros"):
        b, c = st.columns(2)
        rubros = b.multiselect("Rubro", sorted({l["rubro_nombre"] for l in todas if l.get("rubro_nombre")}),
                               key=f"{pre}_rubros", placeholder="Todos")
        regiones = c.multiselect("Región", sorted({l["region"] for l in todas if l.get("region")}),
                                 key=f"{pre}_regiones", placeholder="Todas")
        a, b, c, d = st.columns(4)
        max_dias = a.slider("Cierra en máximo (días)", 0, 30, 30, key=f"{pre}_dias")
        monto_min = b.number_input("Monto mínimo ($)", 0, step=100_000, key=f"{pre}_min")
        monto_max = c.number_input("Monto máximo ($)", 0, step=100_000, key=f"{pre}_max",
                                   help="0 = sin tope. Las que no informan monto se muestran igual.")
        solo_precios = d.toggle("Solo con precios de tiendas", key=f"{pre}_precios")
        plazo = llamado = None
        if compra_agil:
            a, b, _ = st.columns([1, 1, 2])
            plazo_txt = a.selectbox("Entrega en máximo", ["Cualquiera", "2 días", "5 días", "10 días", "30 días"],
                                    key="ca_plazo")
            plazo = None if plazo_txt == "Cualquiera" else int(plazo_txt.split()[0])
            llamado_txt = b.segmented_control("Llamado", ["Todos", "1º", "2º"], default="Todos", key="ca_llamado",
                                              help="1º llamado: solo empresas de menor tamaño. 2º: cualquiera.")
            llamado = {"1º": 1, "2º": 2}.get(llamado_txt)

    lista = filtrar(todas, texto=texto, rubros=rubros, regiones=regiones, max_dias=max_dias if max_dias < 30 else None,
                    monto_min=monto_min or None, monto_max=monto_max or None,
                    con_precios=set(prep["mercado"]) if solo_precios else None, plazo_max=plazo, llamado=llamado)
    st.caption(f"{len(lista)} de {len(todas)} abiertas. Toca una fila para ver el detalle.")
    filas = []
    for l in lista:
        fila = {"Código": l["codigo"], "Nombre": l.get("nombre"), "Organismo": l.get("organismo"),
                "Región": re.sub(r"^Región (de la |del |de )?", "", l.get("region") or ""),
                "Monto ($)": comun.pesos(l.get("monto_estimado")), "Cierre": comun.fecha_hora(l.get("fecha_cierre")),
                "Días": l.get("dias_restantes")}
        if compra_agil:
            fila |= {"Entrega (días)": l.get("plazo_entrega_dias"), "Llamado": l.get("llamado")}
        else:
            fila["Tipo"] = l.get("tipo")
        filas.append(fila | {"Precios": l["codigo"] in prep["mercado"], "Ficha": l.get("url")})
    evento = st.dataframe(
        pd.DataFrame(filas), hide_index=True, on_select="rerun", selection_mode="single-row", key=f"{pre}_tabla",
        height=420, column_config={
            "Nombre": st.column_config.TextColumn(width="large"),
            "Organismo": st.column_config.TextColumn(width="medium"),
            "Monto ($)": st.column_config.NumberColumn(format="localized"),
            "Entrega (días)": st.column_config.NumberColumn(format="%g"),
            "Precios": st.column_config.CheckboxColumn(help="Tiene precios de tiendas buscados por Claude"),
            "Ficha": st.column_config.LinkColumn(display_text="Abrir"),
        })
    if evento.selection.rows:
        ficha(lista[evento.selection.rows[0]], prep)


def ficha(lic: dict, prep: dict) -> None:
    codigo = lic["codigo"]
    with st.container(border=True):
        st.subheader(f"{codigo} · {lic.get('nombre')}")
        st.caption(" · ".join(x for x in (lic.get("organismo"), lic.get("region"), lic.get("comuna")) if x))
        k = st.columns(4)
        k[0].metric("Monto estimado", comun.clp(lic.get("monto_estimado")) if lic.get("monto_estimado") else "—")
        k[1].metric("Cierre", comun.fecha_hora(lic.get("fecha_cierre"), corta=True))
        k[2].metric("Días al cierre", comun.dias_texto(lic.get("dias_restantes")))
        if es_compra_agil(lic):
            plazo = lic.get("plazo_entrega_dias")
            k[3].metric("Plazo de entrega", f"{plazo:g} días" if plazo is not None else "—",
                        help="Desde que aceptas la orden de compra.")
            if lic.get("direccion_entrega"):
                st.markdown(f"**Entrega en:** {lic['direccion_entrega']}")
            if lic.get("llamado") == 1:
                st.info("Primer llamado: solo pueden cotizar empresas de menor tamaño (Mipymes).")
        else:
            k[3].metric("Tipo", lic.get("tipo") or "—")
        st.markdown(f"**Rubro:** {lic.get('rubro_nombre') or '—'} · **Palabras detectadas:** "
                    f"{lic.get('palabras_detectadas') or '—'}")
        if lic.get("alertas_regulatorias"):
            st.warning(f"Requiere registro ISP: {lic['alertas_regulatorias']}.")

        items = prep["items"].get(codigo, [])
        st.markdown(f"**Ítems ({len(items)})**")
        if items:
            st.dataframe(pd.DataFrame([{
                "Línea": it.get("linea"), "Producto": it.get("producto"), "Descripción": it.get("descripcion"),
                "Cantidad": it.get("cantidad"), "Unidad": it.get("unidad"),
                "Pagado por el Estado (mediana)": comun.pesos(it.get("ref_mediana")), "OC comparadas": it.get("ref_n_ordenes"),
            } for it in items]), hide_index=True, column_config={
                "Descripción": st.column_config.TextColumn(width="medium"),
                "Cantidad": st.column_config.NumberColumn(format="%g"),
                "Pagado por el Estado (mediana)": st.column_config.NumberColumn(
                    format="localized", help="Precio unitario neto en órdenes de compra de productos parecidos")})
        else:
            st.caption("El radar no trae los ítems de esta licitación: revísalos en la ficha.")

        mercado = prep["mercado"].get(codigo, [])
        if mercado:
            st.markdown("**Precios de tiendas**")
            st.dataframe(pd.DataFrame([{
                "Línea": op.get("linea"), "Tienda": op.get("tienda"), "Producto": op.get("producto_mercado"),
                "Precio unitario neto": comun.pesos(op.get("precio_unitario_neto")), "Coincidencia": op.get("coincidencia"),
                "Verificado": bool(op.get("verificado")), "Link": op.get("url"),
            } for op in sorted(mercado, key=lambda o: (o.get("linea") or 0, o.get("precio_unitario_neto") or 0))]),
                hide_index=True, column_config={
                    "Precio unitario neto": st.column_config.NumberColumn(format="localized"),
                    "Link": st.column_config.LinkColumn(display_text="Ver")})

        a, b, c = st.columns(3)
        if a.button("Evaluar GO / NO GO", icon="📊", type="primary", width="stretch", key=f"evaluar_{codigo}"):
            comun.ir_a("evaluacion", codigo)
        if b.button("Orden de compra al proveedor", icon="🧾", width="stretch", key=f"oc_{codigo}"):
            comun.ir_a("orden", codigo)
        c.link_button("Abrir en Mercado Público", lic.get("url") or "", icon="🔗", width="stretch")
