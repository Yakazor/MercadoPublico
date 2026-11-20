"""Inicio: cuántas hay abiertas, cuáles cierran pronto y las mejores oportunidades."""
import pandas as pd
import streamlit as st

import comun
import estilo
from radar.evaluacion import CONDICIONADO, GO
from radar.plataforma import es_compra_agil, ranking


def pagina() -> None:
    prep = comun.datos()
    lics, meta = prep["licitaciones"], prep["meta"]
    estilo.encabezado("Oportunidades del Estado para tu negocio", marcada="tu negocio",
                      antetitulo="Radar Mercado Público",
                      subtitulo="Licitaciones y Compras Ágiles abiertas de tus rubros, evaluadas con tus supuestos.")
    col, boton = st.columns([4, 1], vertical_alignment="bottom")
    col.caption(f"Datos publicados: {comun.fecha_hora(meta.get('generado'))} · Compras Ágiles: "
                f"{comun.fecha_hora(meta.get('compras_agiles_generado'))}. Se actualizan solos en GitHub: las "
                "licitaciones cada mañana y las Compras Ágiles cada hora (cada vez que se publican, cambia la hora).")
    if boton.button("Recargar datos", icon="🔄", width="stretch"):
        comun.recargar()
        st.rerun()
    generado = comun.datos_generados(meta)
    if generado is not None and pd.Timestamp.now(tz="America/Santiago") - generado > pd.Timedelta(hours=26):
        st.warning(f"Los datos son del {generado:%d-%m %H:%M}: tienen más de un día.")
        if "actualizar" in comun.PAGINAS:
            st.page_link(comun.PAGINAS["actualizar"], label="Actualizar ahora desde la API", icon="🔄")
    comun.avisar_compras_agiles(meta)

    agiles = [l for l in lics if es_compra_agil(l)]
    pronto = [l for l in lics if l.get("dias_restantes") is not None and l["dias_restantes"] <= 2]
    evaluadas = ranking(prep, comun.supuestos(), comun.margen(), comun.otros(), comun.estimar_oc(), comun.cotizaciones())
    conteo = pd.Series([e.decision for _, _, e in evaluadas]).value_counts()
    # «Evaluadas» = con al menos un precio, sea cual sea la decisión: la misma cifra del Ranking.
    estilo.indicadores([(len(lics) - len(agiles), "Licitaciones abiertas"), (len(agiles), "Compras Ágiles abiertas"),
                        (len(pronto), "Cierran en 2 días o menos"), (len(evaluadas), "Evaluadas (con precio)"),
                        (f"{conteo.get(GO, 0)} / {conteo.get(CONDICIONADO, 0)}", "GO / con condiciones")])

    st.subheader("Mejores oportunidades")
    st.caption("Evaluadas con tus supuestos, de mejor a peor. «Ver evaluación» abre su detalle GO / NO GO.")
    top = evaluadas[:9]
    if not top:
        st.info("Todavía no hay licitaciones abiertas con precios. Activa «Estimar con OC del Estado» en "
                "⚙️ Supuestos o ingresa cotizaciones en Evaluación.")
    else:
        datos = {l["codigo"]: [("Margen neto", f"{(e.margenes['neto_pct'] or 0) * 100:.0f} %"),
                               ("Oferta c/IVA", estilo.monto_corto(e.ingresos["oferta_total"])),
                               ("Cierre", comun.dias_texto(l.get("dias_restantes")))] for l, _, e in top}
        elegida = estilo.grilla([l for l, _, _ in top], prep, {l["codigo"]: e.decision for l, _, e in top},
                                "top", boton="Ver evaluación", datos=datos)
        if elegida:
            comun.ir_a("evaluacion", elegida["codigo"])

    st.subheader("Cierran pronto")
    st.caption("En 2 días o menos, primero las que cierran antes.")
    cierran = sorted(pronto, key=lambda l: l.get("fecha_cierre") or "")[:9]
    if not cierran:
        st.info("Nada cierra en los próximos 2 días.")
    else:
        decisiones = {l["codigo"]: e.decision for l, _, e in evaluadas}
        elegida = estilo.grilla(cierran, prep, decisiones, "pronto", boton="Ver evaluación")
        if elegida:
            comun.ir_a("evaluacion", elegida["codigo"])
