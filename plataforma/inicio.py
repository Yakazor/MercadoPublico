"""Inicio: cuántas hay abiertas, cuáles cierran pronto y las mejores oportunidades."""
import pandas as pd
import streamlit as st

import comun
from radar.evaluacion import CONDICIONADO, GO
from radar.plataforma import es_compra_agil, ranking


def _tabla(df: pd.DataFrame, codigos: list[str], clave: str, **config) -> None:
    """Tabla en la que tocar una fila abre esa licitación en Evaluación."""
    evento = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", key=clave,
                          column_config=config)
    if evento.selection.rows and evento.selection.rows[0] < len(codigos):
        comun.ir_a("evaluacion", codigos[evento.selection.rows[0]])


def pagina() -> None:
    prep = comun.datos()
    lics, meta = prep["licitaciones"], prep["meta"]
    st.title("Radar Mercado Público")
    col, boton = st.columns([4, 1], vertical_alignment="bottom")
    col.caption(f"Datos del radar: {comun.fecha_hora(meta.get('generado'))} · Compras Ágiles: "
                f"{comun.fecha_hora(meta.get('compras_agiles_generado'))}. Se actualizan solos en GitHub.")
    if boton.button("Recargar datos", icon="🔄", width="stretch"):
        comun.recargar()
        st.rerun()
    generado = comun.datos_generados(meta)
    if generado is not None and pd.Timestamp.now(tz="America/Santiago") - generado > pd.Timedelta(hours=26):
        st.warning(f"Los datos son del {generado:%d-%m %H:%M}: tienen más de un día.")
        if "actualizar" in comun.PAGINAS:
            st.page_link(comun.PAGINAS["actualizar"], label="Actualizar ahora desde la API", icon="🔄")

    agiles = [l for l in lics if es_compra_agil(l)]
    pronto = [l for l in lics if l.get("dias_restantes") is not None and l["dias_restantes"] <= 2]
    evaluadas = ranking(prep, comun.supuestos(), comun.margen(), comun.otros(), comun.estimar_oc(), comun.cotizaciones())
    conteo = pd.Series([e.decision for _, _, e in evaluadas]).value_counts()
    k = st.columns(5)
    k[0].metric("Licitaciones abiertas", len(lics) - len(agiles))
    k[1].metric("Compras Ágiles abiertas", len(agiles))
    k[2].metric("Cierran en 2 días o menos", len(pronto))
    k[3].metric("Con precios para evaluar", len(evaluadas))
    k[4].metric("GO / con condiciones", f"{conteo.get(GO, 0)} / {conteo.get(CONDICIONADO, 0)}")

    with st.container():
        st.subheader("Mejores oportunidades")
        st.caption("Evaluadas con tus supuestos, de mejor a peor. Toca una fila para ver su evaluación.")
        top = evaluadas[:15]
        cv = comun.compra_venta_por_codigo()
        df = pd.DataFrame([{
            "Código": l["codigo"], "Nombre": ("⚡ " if es_compra_agil(l) else "") + (l.get("nombre") or ""),
            "Decisión": comun.DECISION_CORTA[e.decision],
            "Compra-venta": comun.COMPRA_VENTA[cv.get(l["codigo"], (None, ""))[0]],
            "Margen neto": (e.margenes["neto_pct"] or 0) * 100,
            "Oferta c/IVA": comun.pesos(e.ingresos["oferta_total"]), "Cierre": comun.dias_texto(l.get("dias_restantes")),
        } for l, _, e in top])
        if df.empty:
            st.info("Todavía no hay licitaciones abiertas con precios. Activa «Estimar con OC del Estado» en "
                    "⚙️ Supuestos o ingresa cotizaciones en Evaluación.")
        else:
            _tabla(df, [l["codigo"] for l, _, _ in top], "inicio_top", **{
                "Código": st.column_config.TextColumn(width=130),
                "Nombre": st.column_config.TextColumn(width=330, help="⚡ = Compra Ágil"),
                "Decisión": st.column_config.TextColumn(width=150),
                "Compra-venta": st.column_config.TextColumn(width=105, help=comun.AYUDA_COMPRA_VENTA),
                "Margen neto": st.column_config.NumberColumn(format="%.0f %%", width=90),
                "Oferta c/IVA": st.column_config.NumberColumn(format="localized", width=110),
                "Cierre": st.column_config.TextColumn(width=80)})
    with st.container():
        st.subheader("Cierran pronto")
        st.caption("En 2 días o menos. Toca una fila para abrir su evaluación.")
        cierran = sorted(pronto, key=lambda l: l.get("fecha_cierre") or "")[:15]
        df = pd.DataFrame([{
            "Código": l["codigo"], "Tipo": "Compra Ágil" if es_compra_agil(l) else l.get("tipo"),
            "Nombre": l.get("nombre"), "Cierre": pd.to_datetime(l.get("fecha_cierre")),
            "Monto": comun.pesos(l.get("monto_estimado")),
        } for l in cierran])
        if df.empty:
            st.info("Nada cierra en los próximos 2 días.")
        else:
            _tabla(df, [l["codigo"] for l in cierran], "inicio_pronto", **{
                "Código": st.column_config.TextColumn(width=160), "Tipo": st.column_config.TextColumn(width=100),
                "Nombre": st.column_config.TextColumn(width=420),
                "Cierre": st.column_config.DatetimeColumn(format="DD-MM HH:mm", width=110),
                "Monto": st.column_config.NumberColumn(format="localized", width=110)})
