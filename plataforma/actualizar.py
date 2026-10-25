"""Actualizar datos: lanza en GitHub las corridas que consultan la API de Mercado Público y
muestra en qué van. Cuando termina un radar, la plataforma vuelve a leer los datos."""
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import comun
from radar.actualizacion import WORKFLOWS, ErrorGitHub, actualizar, corridas, lanzar, motivo_para_no_lanzar
from radar.plataforma import CHILE

ESTADOS = {"en_cola": "⏳ En cola", "in_progress": "🔄 Corriendo"}
RESULTADOS = {"success": "✅ Terminó bien", "failure": "❌ Falló", "cancelled": "⚪ Cancelada",
              "skipped": "⚪ Omitida", "timed_out": "❌ Se pasó del tiempo"}
EVENTOS = {"schedule": "Automática", "workflow_dispatch": "Manual", "push": "Por un cambio"}
TOKEN = """Para lanzarlas desde aquí, la plataforma necesita un token de GitHub:

1. En GitHub: **Settings › Developer settings › Personal access tokens › Fine-grained tokens ›
   Generate new token**.
2. **Repository access:** *Only select repositories* › `Yakazor/MercadoPublico`.
3. **Permissions › Repository permissions › Actions:** *Read and write*. Nada más.
4. Copia el token y agrégalo a los secretos de la plataforma: `github_token = "github_pat_..."`.

Mientras tanto puedes lanzarlas a mano en GitHub › Actions › el workflow › *Run workflow*."""


def _hora(fecha: datetime | None) -> str:
    return fecha.astimezone(CHILE).strftime("%d-%m %H:%M") if fecha else "—"


def _duracion(c: dict) -> str:
    if not c["inicio"]:
        return "—"
    fin = c["fin"] or datetime.now(CHILE)
    minutos = max(0, (fin - c["inicio"]).total_seconds() / 60)
    return f"{minutos:.0f} min" if minutos >= 1 else "< 1 min"


def pagina() -> None:
    st.title("Actualizar datos")
    st.caption("Los datos vienen de la API de Mercado Público y se consultan en GitHub Actions, no en esta página. "
               "Corren solos: Compras Ágiles cada 3 horas (y se publican al terminar), licitaciones los días "
               "hábiles en la mañana y precios de órdenes de compra todos los días.")
    meta = comun.datos()["meta"]
    generado = comun.datos_generados(meta)
    st.markdown(f"**Datos que estás viendo:** publicados el {generado:%d-%m-%Y a las %H:%M}" if generado
                else "**Datos que estás viendo:** sin fecha de publicación")

    token, clave = comun.secreto("github_token"), comun.secreto("clave")
    if not token:
        st.info(TOKEN)
    elif not clave:
        st.warning("Por seguridad, el botón se activa solo si la plataforma tiene clave de acceso (secreto `clave`): "
                   "sin ella, cualquiera con el link podría lanzar corridas.")
    a, b = st.columns([1, 2], vertical_alignment="center")
    if a.button("Actualizar ahora", icon="🔄", type="primary", width="stretch", disabled=not (token and clave)):
        _actualizar(token)
    b.caption("Lanza Compras Ágiles y el radar de licitaciones. El radar tarda unos 3 minutos; las Compras Ágiles, "
              "entre 15 minutos y hora y media. La página se actualiza sola.")
    if token and clave:
        with st.expander("Lanzar un proceso en particular"):
            for workflow, nombre in WORKFLOWS.items():
                if st.button(nombre, key=f"lanzar_{workflow}"):
                    _lanzar_uno(token, workflow)
    if token:
        _seguimiento_vivo(token)
    else:
        _seguimiento(token)


def _actualizar(token: str) -> None:
    try:
        resultado = actualizar(token, corridas(token))
    except (ErrorGitHub, requests.RequestException) as e:
        st.error(f"No se pudo lanzar: {e}")
        return
    for workflow, estado in resultado:
        (st.success if estado == "lanzado" else st.info)(f"{WORKFLOWS[workflow]}: {estado}.")


def _lanzar_uno(token: str, workflow: str) -> None:
    try:
        motivo = motivo_para_no_lanzar(workflow, corridas(token))
        if motivo:
            st.info(f"{WORKFLOWS[workflow]}: {motivo}.")
            return
        lanzar(workflow, token)
        st.success(f"{WORKFLOWS[workflow]}: lanzado.")
    except (ErrorGitHub, requests.RequestException) as e:
        st.error(f"No se pudo lanzar: {e}")


@st.fragment(run_every=30)
def _seguimiento_vivo(token: str) -> None:
    _seguimiento(token)


def _seguimiento(token: str | None) -> None:
    """Últimas corridas; si terminó un radar después de los datos que se ven, los vuelve a leer."""
    st.subheader("Últimas corridas")
    try:
        lista = corridas(token)
    except (ErrorGitHub, requests.RequestException) as e:
        st.warning(f"No se pudo consultar GitHub: {e}")
        return
    generado = comun.datos_generados(comun.datos()["meta"])
    nuevo = next((c for c in lista if c["workflow"] == "radar-diario.yml" and c["resultado"] == "success"), None)
    recargadas = st.session_state.setdefault("radar_recargados", set())
    # El radar publica unos minutos antes de terminar: margen de 5 minutos.
    if nuevo and generado is not None and nuevo["fin"] > generado + pd.Timedelta(minutes=5) \
            and nuevo["id"] not in recargadas:
        recargadas.add(nuevo["id"])
        comun.recargar()
        st.toast("Hay datos nuevos: la plataforma los volvió a leer.", icon="✅")
        st.rerun(scope="app")
    st.dataframe(pd.DataFrame([{
        "Proceso": c["nombre"], "Estado": ESTADOS.get(c["estado"]) or RESULTADOS.get(c["resultado"], c["resultado"]),
        "Inicio": _hora(c["inicio"]), "Duración": _duracion(c), "Cómo": EVENTOS.get(c["evento"], c["evento"]),
        "Detalle": c["url"],
    } for c in lista[:12]]), hide_index=True, column_config={
        "Detalle": st.column_config.LinkColumn(display_text="Ver en GitHub")})
    if token:
        st.caption("Se revisa sola cada 30 segundos.")
