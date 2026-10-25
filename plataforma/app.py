"""Plataforma del radar de Mercado Público.

    streamlit run plataforma/app.py

Licitaciones y Compras Ágiles abiertas de tus rubros (de la rama `datos`), evaluación
GO / NO GO con tus supuestos y cotizaciones, la orden de compra al proveedor, los manuales
en PDF y el botón para actualizar los datos desde la API (lanza los workflows de GitHub).
La clave de acceso, el token de GitHub, el origen de los datos y tus datos de comprador van
en `.streamlit/secrets.toml` (o en los secretos de Streamlit Cloud), nunca en el repositorio.
"""
import hmac

import streamlit as st
from streamlit.components.v1 import html

import actualizar
import comun
import evaluar
import explorar
import inicio
import manuales
import orden

st.set_page_config(page_title="Radar Mercado Público", page_icon="🔎", layout="wide")


def guardar_cookie(valor: str, dias: int) -> None:
    """Guarda (o borra, con 0 días) la llave de acceso en el navegador. Streamlit lee cookies pero no las
    escribe: lo hace un componente invisible al final de la página."""
    html(f"<script>document.cookie = '{comun.COOKIE_ACCESO}={valor}; path=/; max-age={dias * 86400}; "
         "SameSite=Strict; Secure';</script>", height=0)


def acceso() -> bool:
    """Pide la clave, salvo que este navegador la tenga recordada («Recordarme en este equipo»)."""
    clave = comun.secreto("clave")
    if not clave:
        return True
    ss = st.session_state
    llave = comun.token_acceso(clave)
    # Después de «Cerrar sesión» la cookie leída al abrir la página sigue en st.context: no se usa.
    if not ss.get("autorizado") and not ss.get("salio") and hmac.compare_digest(comun.cookie_acceso(), llave):
        ss["autorizado"] = True
    if ss.get("autorizado"):
        if ss.pop("recordar", False):
            ss["cookie_pendiente"] = (llave, comun.DIAS_RECORDAR)
        return True
    if ss.get("salio"):
        ss["cookie_pendiente"] = ("", 0)
    st.title("Radar Mercado Público")
    with st.form("acceso"):
        intento = st.text_input("Clave de acceso", type="password")
        recordar = st.checkbox(f"Recordarme en este equipo ({comun.DIAS_RECORDAR} días)", value=True,
                               help="No pide la clave al recargar la página. No lo uses en computadores compartidos.")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(intento.encode(), str(clave).encode()):
                ss.update(autorizado=True, recordar=recordar, salio=False)
                st.rerun()
            st.error("Clave incorrecta.")
    return False


def boton_salir(contenedor) -> None:
    if comun.secreto("clave") and contenedor.button("Cerrar sesión", icon="🔒", width="stretch",
                                                     help="Olvida la clave en este navegador"):
        st.session_state.update(autorizado=False, salio=True)
        st.rerun()


if acceso():
    comun.conservar_estado("oc_")
    comun.PAGINAS.update({
        "inicio": st.Page(inicio.pagina, title="Inicio", icon="🏠", url_path="inicio", default=True),
        "licitaciones": st.Page(explorar.licitaciones, title="Licitaciones", icon="📋", url_path="licitaciones"),
        "compra_agil": st.Page(explorar.compras_agiles, title="Compras Ágiles", icon="⚡", url_path="compra-agil"),
        "evaluacion": st.Page(evaluar.pagina, title="Evaluación GO / NO GO", icon="📊", url_path="evaluacion"),
        "orden": st.Page(orden.pagina, title="Orden de compra", icon="🧾", url_path="orden-de-compra"),
        "manuales": st.Page(manuales.pagina, title="Manuales", icon="📚", url_path="manuales"),
        "actualizar": st.Page(actualizar.pagina, title="Actualizar datos", icon="🔄", url_path="actualizar"),
    })
    # Menú arriba y sin barra lateral: las tablas usan todo el ancho de la pantalla.
    navegacion = st.navigation(list(comun.PAGINAS.values()), position="top")
    _, supuestos, salir = st.columns([5, 1.3, 1.3], vertical_alignment="center")
    with supuestos.popover("Supuestos", icon="⚙️", width="stretch",
                           help="Margen, otros costos, valor de tu hora, costo financiero y despacho por zona"):
        comun.panel_supuestos()
    boton_salir(salir)
    navegacion.run()

# Al final para no correr el contenido (un st.switch_page antes lo deja para la próxima corrida).
if "cookie_pendiente" in st.session_state:
    guardar_cookie(*st.session_state.pop("cookie_pendiente"))
