"""Lo que comparten las páginas: datos (con caché), supuestos, secretos y formato."""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for _ruta in (RAIZ / "src", RAIZ / "scripts"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit.errors import StreamlitSecretNotFoundError  # noqa: E402

from evaluar_licitaciones import clp  # noqa: E402,F401
from radar.evaluacion import CONDICIONADO, GO  # noqa: E402
from radar.plataforma import ORIGEN_DATOS, leer_datos, preparar, supuestos_config  # noqa: E402

ZONAS = {"cercana": "Región Metropolitana", "media": "Valparaíso, O'Higgins, Maule",
         "lejana": "Coquimbo a Los Ríos", "extrema": "Extremo norte y sur"}
# Páginas (st.Page) por nombre, para los botones que llevan de una a otra. Las llena app.py.
PAGINAS: dict = {}


def secreto(nombre: str, defecto=None):
    """Valor de `.streamlit/secrets.toml` (o de los secretos de Streamlit Cloud)."""
    try:
        return st.secrets.get(nombre, defecto)
    except StreamlitSecretNotFoundError:
        return defecto


@st.cache_data(ttl=1800, show_spinner="Cargando licitaciones…")
def _leer(origen: str) -> dict:
    return leer_datos(origen)


def datos() -> dict:
    """Licitaciones y Compras Ágiles abiertas (se vuelven a bajar cada 30 minutos)."""
    origen = os.environ.get("RADAR_DATOS") or secreto("datos") or ORIGEN_DATOS
    return preparar(_leer(origen))


def recargar() -> None:
    _leer.clear()


@st.cache_data
def _supuestos_base() -> dict:
    return supuestos_config()


def supuestos() -> dict:
    """Supuestos de `config.yaml` con lo que cambiaste en la barra lateral."""
    s = dict(_supuestos_base())
    s["valor_hora"] = st.session_state.get("sup_valor_hora", s["valor_hora"])
    s["tasa_financiera_mensual"] = st.session_state.get("sup_tasa", s["tasa_financiera_mensual"] * 100) / 100
    s["logistica_pct"] = {z: st.session_state.get(f"sup_log_{z}", v * 100) / 100 for z, v in s["logistica_pct"].items()}
    return s


def margen() -> float:
    return st.session_state.get("sup_margen", 20) / 100


def otros() -> float:
    return st.session_state.get("sup_otros", 5) / 100


def estimar_oc() -> bool:
    return st.session_state.get("sup_estimar_oc", False)


def cotizaciones() -> dict:
    """{código: {línea: precio unitario neto}} que ingresaste en Evaluación."""
    return st.session_state.setdefault("cotizaciones", {})


def panel_supuestos() -> None:
    """Supuestos de la evaluación en la barra lateral (valen para todas las páginas)."""
    base = _supuestos_base()
    with st.sidebar.expander("Supuestos de evaluación"):
        st.number_input("Margen sobre el costo (%)", 0, 200, 20, 1, key="sup_margen")
        st.number_input("Otros costos (%)", 0, 50, 5, 1, key="sup_otros",
                        help="Boletas, envases y gastos menores sobre el costo de la mercadería.")
        st.number_input("Valor de tu hora ($)", 0, 100_000, int(base["valor_hora"]), 500, key="sup_valor_hora")
        st.number_input("Costo financiero mensual (%)", 0.0, 10.0, base["tasa_financiera_mensual"] * 100, 0.1,
                        key="sup_tasa", help="Financiar la compra hasta que el Estado paga (30 días).")
        st.caption("Despacho desde Santiago (% del costo de la mercadería)")
        for zona, pct in base["logistica_pct"].items():
            st.number_input(f"{zona.capitalize()}: {ZONAS[zona]}", 0.0, 50.0, pct * 100, 0.5, key=f"sup_log_{zona}")
        st.toggle("Estimar con OC del Estado las líneas sin precio", key="sup_estimar_oc",
                  help="Para las líneas sin precio de tienda ni cotización usa el costo máximo que permite "
                       "ofertar lo que pagó el Estado (mediana de órdenes de compra). Es una estimación: "
                       "la evaluación la marca como precio aproximado.")


def conservar_estado(*prefijos: str) -> None:
    """Streamlit borra el valor de un widget cuando su página no se muestra; reasignarlo al
    inicio de cada corrida lo conserva al cambiar de página."""
    for clave in list(st.session_state):
        if clave.startswith(prefijos):
            st.session_state[clave] = st.session_state[clave]


def pesos(valor) -> int | None:
    """Monto redondeado al peso para las tablas (sin decimales)."""
    return None if valor is None or pd.isna(valor) else round(valor)


def con_signo(valor: float) -> str:
    """Monto con el signo adelante, para que st.metric lo muestre en rojo si es negativo."""
    return f"-{clp(abs(valor))}" if valor < 0 else clp(valor)


def fecha_hora(texto: str | None, corta: bool = False) -> str:
    if not texto:
        return "—"
    return pd.Timestamp(texto).strftime("%d-%m %H:%M" if corta else "%d-%m-%Y %H:%M")


def dias_texto(dias) -> str:
    if dias is None:
        return "—"
    return "hoy" if dias == 0 else "mañana" if dias == 1 else f"{dias} días"


def ir_a(pagina: str, codigo: str | None = None) -> None:
    """Abre otra página con esa licitación elegida (en Orden de compra, con sus ítems cargados)."""
    if codigo:
        st.session_state["codigo"] = codigo
        if pagina == "orden":
            st.session_state["pedido_oc"] = codigo
    st.switch_page(PAGINAS[pagina])


def aviso_decision(ev) -> None:
    texto = f"**{ev.etiqueta}** · {ev.recomendacion}"
    {GO: st.success, CONDICIONADO: st.warning}.get(ev.decision, st.error)(texto)
