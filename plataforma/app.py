"""Plataforma del radar de Mercado Público.

    streamlit run plataforma/app.py

Licitaciones y Compras Ágiles abiertas de tus rubros (de la rama `datos`), evaluación
GO / NO GO con tus supuestos y cotizaciones, y la orden de compra al proveedor. La
clave de acceso, el origen de los datos y tus datos de comprador van en
`.streamlit/secrets.toml` (o en los secretos de Streamlit Cloud), nunca en el repositorio.
"""
import hmac

import streamlit as st

import comun
import evaluar
import explorar
import inicio
import orden

st.set_page_config(page_title="Radar Mercado Público", page_icon="🔎", layout="wide")


def acceso() -> bool:
    clave = comun.secreto("clave")
    if not clave or st.session_state.get("autorizado"):
        return True
    st.title("Radar Mercado Público")
    with st.form("acceso"):
        intento = st.text_input("Clave de acceso", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(intento.encode(), str(clave).encode()):
                st.session_state["autorizado"] = True
                st.rerun()
            st.error("Clave incorrecta.")
    return False


if acceso():
    comun.conservar_estado("oc_")
    comun.PAGINAS.update({
        "inicio": st.Page(inicio.pagina, title="Inicio", icon="🏠", url_path="inicio", default=True),
        "licitaciones": st.Page(explorar.licitaciones, title="Licitaciones", icon="📋", url_path="licitaciones"),
        "compra_agil": st.Page(explorar.compras_agiles, title="Compras Ágiles", icon="⚡", url_path="compra-agil"),
        "evaluacion": st.Page(evaluar.pagina, title="Evaluación GO / NO GO", icon="📊", url_path="evaluacion"),
        "orden": st.Page(orden.pagina, title="Orden de compra", icon="🧾", url_path="orden-de-compra"),
    })
    navegacion = st.navigation(list(comun.PAGINAS.values()))
    comun.panel_supuestos()
    navegacion.run()
