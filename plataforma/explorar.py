"""Licitaciones y Compras Ágiles abiertas: filtros, tabla y ficha con sus ítems."""
import pandas as pd
import streamlit as st

import comun
from radar.evaluacion import CONDICIONADO, GO, NO_GO
from radar.plataforma import es_compra_agil, filtrar, ranking

DECISIONES = [comun.DECISION_CORTA[GO], comun.DECISION_CORTA[CONDICIONADO], comun.DECISION_CORTA[NO_GO],
              comun.SIN_EVALUAR]
OPCIONES_CV = ["Todas", *comun.COMPRA_VENTA.values()]


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

    a, b, c = st.columns([2, 1.4, 1.6], vertical_alignment="bottom")
    texto = a.text_input("Buscar", placeholder="código, nombre, organismo o producto", key=f"{pre}_texto")
    decisiones = b.multiselect("Decisión", DECISIONES, key=f"{pre}_decision", placeholder="Todas",
                               help="GO / NO GO con tus supuestos (⚙️ Supuestos). ⚪ = todavía sin precios para "
                                    "evaluar: ingresa cotizaciones o activa «Estimar con OC del Estado».")
    cv_txt = c.segmented_control("Compra y venta directa", OPCIONES_CV, default="Todas", required=True,
                                 key=f"{pre}_cv", help=comun.AYUDA_COMPRA_VENTA)
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
    evaluadas = {l["codigo"]: comun.DECISION_CORTA[e.decision] for l, _, e in ranking(
        prep, comun.supuestos(), comun.margen(), comun.otros(), comun.estimar_oc(), comun.cotizaciones())}
    cv = comun.compra_venta_por_codigo()
    if decisiones:
        lista = [l for l in lista if evaluadas.get(l["codigo"], comun.SIN_EVALUAR) in decisiones]
    if cv_txt != "Todas":
        estado = next(k for k, v in comun.COMPRA_VENTA.items() if v == cv_txt)
        lista = [l for l in lista if cv.get(l["codigo"], (None, ""))[0] is estado]
    st.caption(f"{len(lista)} de {len(todas)} abiertas. 💲 = tiene precios de tiendas. Toca una fila para ver el "
               "detalle, con el organismo, los ítems y el link a Mercado Público.")
    filas = []
    for l in lista:
        fila = {"Código": l["codigo"], "Nombre": ("💲 " if l["codigo"] in prep["mercado"] else "") + (l.get("nombre") or ""),
                "Decisión": evaluadas.get(l["codigo"], comun.SIN_EVALUAR),
                "Compra-venta": comun.COMPRA_VENTA[cv.get(l["codigo"], (None, ""))[0]]}
        if not compra_agil:
            fila["Organismo"] = l.get("organismo")
        fila |= {"Región": comun.region_corta(l.get("region")), "Monto ($)": comun.pesos(l.get("monto_estimado")),
                 "Cierre": pd.to_datetime(l.get("fecha_cierre")), "Días": l.get("dias_restantes")}
        if compra_agil:
            fila |= {"Entrega": l.get("plazo_entrega_dias"), "Llamado": l.get("llamado")}
        filas.append(fila)
    # Anchos fijos: la tabla cabe en una pantalla de notebook (1366 px, menú arriba: ~1.200 px útiles).
    comunes = {"Decisión": 140, "Compra-venta": 105, "Región": 105, "Cierre": 110, "Días": 50}
    anchos = ({"Código": 150, "Nombre": 235, "Monto ($)": 90, "Entrega": 70, "Llamado": 60} if compra_agil else
              {"Código": 125, "Nombre": 255, "Organismo": 140, "Monto ($)": 95}) | comunes
    config = {col: st.column_config.TextColumn(width=ancho) for col, ancho in anchos.items()}
    config["Compra-venta"] = st.column_config.TextColumn(width=anchos["Compra-venta"], help=comun.AYUDA_COMPRA_VENTA)
    config |= {
        "Monto ($)": st.column_config.NumberColumn(format="localized", width=anchos["Monto ($)"]),
        "Cierre": st.column_config.DatetimeColumn(format="DD-MM HH:mm", width=anchos["Cierre"]),
        "Días": st.column_config.NumberColumn(width=anchos["Días"], help="Días que faltan para el cierre"),
    }
    if compra_agil:
        config |= {"Entrega": st.column_config.NumberColumn(format="%g d", width=anchos["Entrega"],
                                                            help="Días para entregar desde la orden de compra"),
                   "Llamado": st.column_config.NumberColumn(width=anchos["Llamado"],
                                                            help="1 = solo empresas de menor tamaño; 2 = todas")}
    evento = st.dataframe(
        pd.DataFrame(filas), hide_index=True, on_select="rerun", selection_mode="single-row", key=f"{pre}_tabla",
        height=420, column_config=config)
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
        estado, motivo = comun.compra_venta_por_codigo().get(codigo, (None, "Sin datos de sus ítems"))
        st.markdown(f"**Compra y venta directa:** {comun.COMPRA_VENTA[estado]} — {motivo}.")
        if lic.get("alertas_regulatorias"):
            st.warning(f"Requiere registro ISP: {lic['alertas_regulatorias']}.")

        items = prep["items"].get(codigo, [])
        st.markdown(f"**Ítems ({len(items)})**")
        if items:
            st.dataframe(pd.DataFrame([{
                "Línea": it.get("linea"), "Producto": it.get("producto"), "Descripción": it.get("descripcion"),
                "Cantidad": it.get("cantidad"), "Unidad": it.get("unidad"),
                "Pagado Estado": comun.pesos(it.get("ref_mediana")), "N° OC": it.get("ref_n_ordenes"),
            } for it in items]), hide_index=True, column_config={
                "Línea": st.column_config.NumberColumn(width=50),
                "Producto": st.column_config.TextColumn(width=170),
                "Descripción": st.column_config.TextColumn(width=270),
                "Cantidad": st.column_config.NumberColumn(format="%g", width=75),
                "Unidad": st.column_config.TextColumn(width=65),
                "Pagado Estado": st.column_config.NumberColumn(
                    format="localized", width=110,
                    help="Mediana del precio unitario neto en órdenes de compra de productos parecidos"),
                "N° OC": st.column_config.NumberColumn(width=60, help="Órdenes de compra comparadas")})
        else:
            st.caption("El radar no trae los ítems de esta licitación: revísalos en la ficha.")

        mercado = prep["mercado"].get(codigo, [])
        if mercado:
            st.markdown("**Precios de tiendas**")
            st.dataframe(pd.DataFrame([{
                "Línea": op.get("linea"), "Tienda": op.get("tienda"), "Producto": op.get("producto_mercado"),
                "Precio neto": comun.pesos(op.get("precio_unitario_neto")), "Coincidencia": op.get("coincidencia"),
                "Verificado": bool(op.get("verificado")), "Link": op.get("url"),
            } for op in sorted(mercado, key=lambda o: (o.get("linea") or 0, o.get("precio_unitario_neto") or 0))]),
                hide_index=True, column_config={
                    "Línea": st.column_config.NumberColumn(width=50),
                    "Tienda": st.column_config.TextColumn(width=110),
                    "Producto": st.column_config.TextColumn(width=250),
                    "Precio neto": st.column_config.NumberColumn(format="localized", width=100,
                                                                 help="Precio unitario sin IVA"),
                    "Coincidencia": st.column_config.TextColumn(width=100),
                    "Verificado": st.column_config.CheckboxColumn(width=80),
                    "Link": st.column_config.LinkColumn(display_text="Ver", width=50)})
        elif items:
            comun.pedir_precios(codigo, es_compra_agil(lic))

        a, b, c = st.columns(3)
        if a.button("Evaluar GO / NO GO", icon="📊", type="primary", width="stretch", key=f"evaluar_{codigo}"):
            comun.ir_a("evaluacion", codigo)
        # La clave no puede empezar con «oc_»: app.py conserva esas claves reasignándolas y Streamlit no
        # deja asignar el valor de un botón (StreamlitValueAssignmentNotAllowedError).
        if b.button("Orden de compra al proveedor", icon="🧾", width="stretch", key=f"ir_oc_{codigo}"):
            comun.ir_a("orden", codigo)
        c.link_button("Abrir en Mercado Público", lic.get("url") or "", icon="🔗", width="stretch")
