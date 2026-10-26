"""Lo que comparten las páginas: datos (con caché), supuestos, secretos y formato."""
import hashlib
import hmac
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for _ruta in (RAIZ / "src", RAIZ / "scripts"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit.errors import StreamlitSecretNotFoundError, StreamlitValueAssignmentNotAllowedError  # noqa: E402

from evaluar_licitaciones import clp  # noqa: E402,F401
from radar.evaluacion import CONDICIONADO, GO, NO_GO  # noqa: E402
from radar.filtro import normalizar  # noqa: E402
from radar.plataforma import (ORIGEN_DATOS, compra_venta, leer_datos, origen_en_commit, preparar,  # noqa: E402
                              supuestos_config, version_datos)

ZONAS = {"cercana": "Región Metropolitana", "media": "Valparaíso, O'Higgins, Maule",
         "lejana": "Coquimbo a Los Ríos", "extrema": "Extremo norte y sur"}
# Páginas (st.Page) por nombre, para los botones que llevan de una a otra. Las llena app.py.
PAGINAS: dict = {}
# «Recordarme en este equipo»: cookie con una llave derivada de la clave, por estos días.
COOKIE_ACCESO = "radar_acceso"
DIAS_RECORDAR = 30
# Textos cortos para que las tablas quepan en una pantalla de notebook (~900 px de ancho útil).
DECISION_CORTA = {GO: "🟢 GO", CONDICIONADO: "🟡 Con condiciones", NO_GO: "🔴 NO GO"}
SIN_EVALUAR = "⚪ Sin evaluar"
COMPRA_VENTA = {True: "✅ Sí", False: "❌ No", None: "❓ Revisar"}
AYUDA_COMPRA_VENTA = ("Compra y venta directa: productos que compras hechos y revendes. ❌ = incluye un servicio "
                      "(instalación, mantención, confección, arriendo, capacitación, licencias) o exige registro ISP. "
                      "❓ = la cantidad o el producto exacto están en las bases.")
_REGIONES = [("arica", "Arica"), ("tarapaca", "Tarapacá"), ("antofagasta", "Antofagasta"), ("atacama", "Atacama"),
             ("coquimbo", "Coquimbo"), ("valparaiso", "Valparaíso"), ("metropolitana", "Metropolitana"),
             ("higgins", "O'Higgins"), ("maule", "Maule"), ("nuble", "Ñuble"), ("biobio", "Biobío"),
             ("araucania", "Araucanía"), ("los rios", "Los Ríos"), ("los lagos", "Los Lagos"), ("aysen", "Aysén"),
             ("magallanes", "Magallanes")]


def secreto(nombre: str, defecto=None):
    """Valor de `.streamlit/secrets.toml` (o de los secretos de Streamlit Cloud)."""
    try:
        return st.secrets.get(nombre, defecto)
    except StreamlitSecretNotFoundError:
        return defecto


def token_acceso(clave: str) -> str:
    """Lo que el navegador guarda para no pedir la clave en cada visita. Se deriva de la clave (no es la
    clave): si cambias la clave en los secretos, todos los navegadores recordados vuelven a pedirla."""
    return hmac.new(str(clave).encode(), b"radar-mercadopublico/acceso", hashlib.sha256).hexdigest()


def cookie_acceso() -> str:
    """La llave guardada en este navegador (Streamlit lee las cookies al abrir la página). Fuera de un
    navegador (pruebas con AppTest) no hay cookies reales."""
    valor = st.context.cookies.get(COOKIE_ACCESO)
    return valor if isinstance(valor, str) else ""


@st.cache_data(ttl=1800, show_spinner="Cargando licitaciones…")
def _leer(origen: str, marca: str | None) -> dict:
    return leer_datos(origen, marca=marca)


@st.cache_data(ttl=60, show_spinner=False)
def _version(origen: str) -> str | None:
    return version_datos(origen)


def _origen() -> str:
    """De dónde se leen los datos. La rama `datos` de GitHub se lee en su último commit (se revisa
    cada minuto): una publicación nueva (p. ej. precios recién cotizados) se ve al tiro, sin
    esperar que venza la caché de 30 minutos."""
    origen = os.environ.get("RADAR_DATOS") or secreto("datos") or ORIGEN_DATOS
    return origen_en_commit(origen, _version(origen))


def datos() -> dict:
    """Licitaciones y Compras Ágiles abiertas (se vuelven a bajar con cada publicación nueva)."""
    return preparar(_leer(_origen(), st.session_state.get("marca_datos")))


@st.cache_data(ttl=1800, show_spinner=False)
def _compra_venta(origen: str, marca: str | None) -> dict:
    prep = preparar(_leer(origen, marca))
    return {l["codigo"]: compra_venta(l, prep["items"].get(l["codigo"], [])) for l in prep["licitaciones"]}


def compra_venta_por_codigo() -> dict:
    """{código: (sí / no / None = revisar, motivo)} de las abiertas (se calcula una vez por descarga)."""
    return _compra_venta(_origen(), st.session_state.get("marca_datos"))


def recargar() -> None:
    """Vuelve a bajar los datos, saltándose la caché de GitHub."""
    _leer.clear()
    _version.clear()
    st.session_state["marca_datos"] = pd.Timestamp.now().strftime("%Y%m%d%H%M%S")


def datos_generados(meta: dict) -> pd.Timestamp | None:
    """Cuándo publicó el radar los datos que se están mostrando (hora de Chile)."""
    try:
        return pd.Timestamp(meta["generado"]).tz_convert("America/Santiago")
    except (KeyError, TypeError, ValueError):
        return None


@st.cache_data
def _supuestos_base() -> dict:
    return supuestos_config()


def supuestos() -> dict:
    """Supuestos de `config.yaml` con lo que cambiaste en ⚙️ Supuestos."""
    s = dict(_supuestos_base())
    s["valor_hora"] = st.session_state.get("sup_valor_hora", s["valor_hora"])
    s["tasa_financiera_mensual"] = st.session_state.get("sup_tasa", s["tasa_financiera_mensual"] * 100) / 100
    s["logistica_pct"] = {z: st.session_state.get(f"sup_log_{z}", v * 100) / 100 for z, v in s["logistica_pct"].items()}
    s["recupera_iva_compras"] = st.session_state.get("sup_recupera_iva", s["recupera_iva_compras"])
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
    """Supuestos de la evaluación (botón ⚙️ Supuestos, arriba en todas las páginas)."""
    base = _supuestos_base()
    with st.container():
        st.number_input("Margen sobre el costo (%)", 0, 200, 20, 1, key="sup_margen")
        st.number_input("Otros costos (%)", 0, 50, 5, 1, key="sup_otros",
                        help="Boletas, envases y gastos menores sobre el costo de la mercadería.")
        st.number_input("Valor de tu hora ($)", 0, 100_000, int(base["valor_hora"]), 500, key="sup_valor_hora")
        st.number_input("Costo financiero mensual (%)", 0.0, 10.0, base["tasa_financiera_mensual"] * 100, 0.1,
                        key="sup_tasa", help="Financiar la compra hasta que el Estado paga (30 días).")
        st.caption("Despacho desde Santiago (% del costo de la mercadería)")
        for zona, pct in base["logistica_pct"].items():
            st.number_input(f"{zona.capitalize()}: {ZONAS[zona]}", 0.0, 50.0, pct * 100, 0.5, key=f"sup_log_{zona}")
        st.toggle("Recupero el IVA de mis compras (crédito fiscal)", value=bool(base["recupera_iva_compras"]),
                  key="sup_recupera_iva",
                  help="Apagado: el IVA que pagas al comprar es costo tuyo (y el de la venta se paga entero al "
                       "SII), así que costos y ofertas se calculan con el precio con IVA. Enciéndelo cuando "
                       "factures con un giro con IVA y compres con factura a tu nombre.")
        st.toggle("Estimar con OC del Estado las líneas sin precio", key="sup_estimar_oc",
                  help="Para las líneas sin precio de tienda ni cotización usa el costo máximo que permite "
                       "ofertar lo que pagó el Estado (mediana de órdenes de compra). Es una estimación: "
                       "la evaluación la marca como precio aproximado.")


def conservar_estado(*prefijos: str) -> None:
    """Streamlit borra el valor de un widget cuando su página no se muestra; reasignarlo al
    inicio de cada corrida lo conserva al cambiar de página. Botones, tablas con selección y
    cargas de archivo no se pueden reasignar (Streamlit lo prohíbe) y se saltan."""
    for clave in list(st.session_state):
        if clave.startswith(prefijos):
            try:
                st.session_state[clave] = st.session_state[clave]
            except StreamlitValueAssignmentNotAllowedError:
                pass


def pedir_precios(codigo: str, compra_agil: bool) -> None:
    """Cómo pedirle a Claude precios de tiendas para una licitación que todavía no los tiene."""
    tipo = "Compra Ágil" if compra_agil else "licitación"
    st.caption(f"Sin precios de tiendas: la rutina diaria de Claude los busca solo para 4 licitaciones por día "
               f"(2 Compras Ágiles). Para pedirlos para esta {tipo}, copia este texto en la app de Claude, en la "
               "sesión «Rutina: Actualizar Radar de Licitaciones». Cuando termine, toca «Recargar datos» en Inicio.")
    st.code(f"PRECIOS para: {codigo}", language=None)


def pesos(valor) -> int | None:
    """Monto redondeado al peso para las tablas (sin decimales)."""
    return None if valor is None or pd.isna(valor) else round(valor)


def con_signo(valor: float) -> str:
    """Monto con el signo adelante, para que st.metric lo muestre en rojo si es negativo."""
    return f"-{clp(abs(valor))}" if valor < 0 else clp(valor)


def region_corta(region: str | None) -> str:
    texto = normalizar(region or "")
    return next((corta for clave, corta in _REGIONES if clave in texto), region or "")


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


def md(texto: str) -> str:
    """Texto para st.markdown y los avisos: Streamlit lee lo que va entre dos «$» como fórmula
    (LaTeX), así que «la oferta ($881.874) supera el monto ($800.000)» salía pegado y en cursiva."""
    return str(texto).replace("$", r"\$")


def numero_texto(valor) -> str:
    """Número para una tabla chica de solo lectura: «72.450», o «—» si falta (Streamlit muestra
    «None» en las celdas vacías de una columna numérica y no tiene opción para cambiarlo)."""
    return "—" if valor is None or pd.isna(valor) else f"{round(valor):,}".replace(",", ".")


def aviso_decision(ev) -> None:
    texto = md(f"**{ev.etiqueta}** · {ev.recomendacion}")
    {GO: st.success, CONDICIONADO: st.warning}.get(ev.decision, st.error)(texto)
