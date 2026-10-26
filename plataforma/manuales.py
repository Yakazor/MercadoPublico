"""Manuales y documentos en PDF: las guías para operar, las plantillas y los informes que
generan los workflows (presupuestos y evaluaciones)."""
import re
from urllib.parse import quote

import streamlit as st

import comun
from radar.actualizacion import RAMA, REPO

MANUALES = [
    ("Manual: órdenes de compra en Mercado Público", "manuales/Manual_orden_de_compra.pdf",
     "Requisitos para vender al Estado, el ciclo de la licitación al pago, cómo aceptar la OC, tu orden al "
     "proveedor y qué aplicación usar para cada cosa.", "https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W"),
    ("Manual: guía de despacho y factura electrónica", "manuales/Manual_guia_de_despacho_y_factura.pdf",
     "Paso a paso en el facturador gratuito del SII: guía de despacho (52), factura (33) con la referencia 801 "
     "a la OC, y los errores que retrasan el pago.", "https://claude.ai/artifact/XSskNUJg2g5E1HFud8UQ5U"),
    ("Guía del Radar de Licitaciones", "informes/Guia_Radar_Licitaciones.pdf",
     "Cómo funciona el radar, cómo leer los informes y cómo postular a Mercado Público.", None),
]
PLANTILLAS = [("Orden de compra, persona natural", "proveedores/plantillas/Plantilla_Orden_de_Compra_Persona_Natural.xlsx"),
              ("Orden de compra, empresa", "proveedores/plantillas/Plantilla_Orden_de_Compra_Empresa.xlsx")]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TITULOS = {"Evaluacion_resumen.pdf": "Evaluación comercial: resumen del día",
           "Indice_de_presupuestos.pdf": "Índice de presupuestos",
           "Grupos_de_licitaciones.pdf": "Grupos de licitaciones (segmentos ONU)"}


def _en_github(ruta: str) -> str:
    return f"https://github.com/{REPO}/blob/{RAMA}/{quote(ruta)}"


def pdfs_de(codigo: str) -> list[tuple[str, str]]:
    """Los PDF de una licitación en informes/pdf/ (presupuesto, ficha GO / NO GO, informe ejecutivo)."""
    carpeta = comun.RAIZ / "informes/pdf"
    if not carpeta.exists():
        return []
    salida = []
    for archivo in sorted(carpeta.glob(f"*_{codigo}*.pdf")):
        m = re.search(r"\d+-\d+-[A-Z0-9]+", archivo.name)
        if m and m.group(0) == codigo:
            salida.append((_tipo(archivo.name), f"informes/pdf/{archivo.name}"))
    return salida


def _tipo(nombre: str) -> str:
    return ("Ficha GO / NO GO" if nombre.endswith("_go_no_go.pdf") else
            "Informe ejecutivo" if nombre.endswith("_informe.pdf") else "Presupuesto")


def descarga(etiqueta: str, ruta: str, mime: str = "application/pdf", clave: str | None = None, **kw) -> None:
    archivo = comun.RAIZ / ruta
    if archivo.exists():
        st.download_button(etiqueta, archivo.read_bytes(), archivo.name, mime, key=clave or ruta, **kw)
    else:
        st.caption(f"{archivo.name}: todavía no está en esta versión.")


def pagina() -> None:
    st.title("Manuales")
    st.caption("Guías para operar en Mercado Público y los documentos que genera el radar. Descarga el PDF o "
               "ábrelo en GitHub para verlo en el navegador.")

    for titulo, ruta, descripcion, editable in MANUALES:
        with st.container(border=True):
            st.markdown(f"**{titulo}**")
            st.caption(descripcion)
            a, b, c = st.columns(3)
            with a:
                descarga("Descargar PDF", ruta, icon="📥", width="stretch")
            b.link_button("Ver en GitHub", _en_github(ruta), icon="📄", width="stretch")
            if editable:
                c.link_button("Versión editable (Claude)", editable, icon="✏️", width="stretch")
    erratas = comun.RAIZ / "informes/Guia_erratas.md"
    if erratas.exists():
        with st.expander("Erratas y actualizaciones de la Guía del Radar"):
            st.markdown(erratas.read_text(encoding="utf-8").split("\n", 1)[-1])

    st.subheader("Plantillas")
    columnas = st.columns(len(PLANTILLAS))
    for col, (titulo, ruta) in zip(columnas, PLANTILLAS):
        with col:
            descarga(titulo, ruta, XLSX, icon="📥", width="stretch")
    st.caption("La página «Orden de compra» las llena por ti.")

    st.subheader("Informes en PDF")
    st.caption("Los regenera GitHub cada vez que la rutina sube precios nuevos (workflow «Verificar precios e "
               "informes PDF»).")
    carpeta = comun.RAIZ / "informes/pdf"
    pdfs = sorted(p.name for p in carpeta.glob("*.pdf")) if carpeta.exists() else []
    generales = [n for n in pdfs if not re.search(r"\d+-\d+-[A-Z0-9]+", n)]
    for nombre in generales:
        descarga(TITULOS.get(nombre, nombre.removesuffix(".pdf").replace("_", " ")), f"informes/pdf/{nombre}",
                  icon="📄")
    por_codigo: dict[str, list[str]] = {}
    for nombre in pdfs:
        m = re.search(r"\d+-\d+-[A-Z0-9]+", nombre)
        if m:
            por_codigo.setdefault(m.group(0), []).append(nombre)
    if por_codigo:
        inicial = st.session_state.get("codigo")
        codigos = sorted(por_codigo)
        codigo = st.selectbox("Presupuesto y evaluación de una licitación", codigos,
                              index=codigos.index(inicial) if inicial in codigos else None,
                              placeholder=f"Elige una de las {len(codigos)} licitaciones con informe")
        if codigo:
            for nombre in por_codigo[codigo]:
                descarga(f"{_tipo(nombre)} ({codigo})", f"informes/pdf/{nombre}", icon="📄")
