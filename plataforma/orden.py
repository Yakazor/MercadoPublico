"""Orden de compra al proveedor: formulario, totales y descarga en Excel (y PDF con LibreOffice).

Nada se guarda en el servidor ni en el repositorio: la orden trae RUT y datos personales.
Se descarga el Excel y, si quieres retomarla después, sus datos en JSON.
"""
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import comun
from orden_proveedor import CARPETA, guardar
from radar.config import hoy_chile
from radar.orden_proveedor import CAMPOS_COMPRADOR, CONDICIONES, crear_orden, siguiente_numero, totales, validar
from radar.plataforma import datos_orden, es_compra_agil, evaluar_licitacion, opciones, orden_xlsx

COLUMNAS = {"codigo": "Código", "descripcion": "Descripción", "unidad": "Unidad", "cantidad": "Cantidad",
            "precio_unitario_neto": "Precio unitario neto", "precio_con_iva": "Precio unitario c/IVA"}
TIPOS = {"persona_natural": "Persona natural con giro", "empresa": "Empresa"}
PROVEEDOR = [("Razón social", "razon_social"), ("RUT", "rut"), ("Vendedor", "vendedor"), ("Contacto", "contacto")]
CONDICIONES_INICIALES = {"flete": "Incluido", "forma_pago": "Transferencia contra entrega",
                         "validez": "Proveedor confirma stock y precio por escrito al aceptar esta OC"}


def _tabla(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{col: it.get(campo) for campo, col in COLUMNAS.items()} for it in items],
                      columns=list(COLUMNAS.values()))
    for col in ("Cantidad", "Precio unitario neto", "Precio unitario c/IVA"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("Código", "Descripción", "Unidad"):
        df[col] = df[col].fillna("").astype(str)
    return df


def _poner_items(items: list[dict]) -> None:
    """Reemplaza los ítems del editor (una versión nueva del editor para que tome los datos)."""
    st.session_state["oc_items"] = _tabla(items)
    st.session_state["oc_version"] = st.session_state.get("oc_version", 0) + 1


def _iniciar() -> None:
    """Valores iniciales: tus datos de comprador vienen de los secretos (no del repositorio)."""
    comprador = dict(comun.secreto("comprador") or {})
    st.session_state.setdefault("oc_numero", siguiente_numero(CARPETA))
    st.session_state.setdefault("oc_fecha", hoy_chile())
    st.session_state.setdefault("oc_tipo", comprador.get("tipo", "persona_natural"))
    for campos in CAMPOS_COMPRADOR.values():
        for _, campo in campos:
            st.session_state.setdefault(f"oc_comp_{campo}", comprador.get(campo, ""))
    for _, campo in PROVEEDOR:
        st.session_state.setdefault(f"oc_prov_{campo}", "")
    st.session_state.setdefault("oc_ref_licitacion", "")
    st.session_state.setdefault("oc_ref_oc_estado", "")
    st.session_state.setdefault("oc_descuento", 0)
    for _, campo in CONDICIONES:
        st.session_state.setdefault(f"oc_cond_{campo}", None if campo == "fecha_entrega" else
                                    CONDICIONES_INICIALES.get(campo, ""))
    if "oc_items" not in st.session_state:
        _poner_items([])


def _cargar_licitacion(codigo: str, tienda: str | None) -> None:
    prep = comun.datos()
    lic = next((l for l in prep["licitaciones"] if l["codigo"] == codigo), None)
    items = prep["items"].get(codigo, [])
    if not lic or not items:
        st.session_state["oc_aviso"] = f"{codigo}: no hay ítems para cargar."
        return
    ops = opciones(items, prep["mercado"].get(codigo, []), comun.cotizaciones().get(codigo), comun.estimar_oc(),
                   comun.margen(), comun.otros())
    p, _ = evaluar_licitacion(lic, items, ops, comun.supuestos(), comun.margen(), comun.otros())
    datos = datos_orden(lic, p, tienda)
    _poner_items(datos["items"])
    st.session_state["oc_ref_licitacion"] = codigo
    if datos["condiciones"].get("lugar_entrega"):
        st.session_state["oc_cond_lugar_entrega"] = datos["condiciones"]["lugar_entrega"]
    elif lic.get("organismo"):
        st.session_state["oc_cond_lugar_entrega"] = f"{lic['organismo']} (dirección de la OC del Estado)"
    if es_compra_agil(lic) and lic.get("plazo_entrega_dias") is not None:
        st.session_state["oc_cond_observaciones"] = (f"Compra Ágil {codigo}: plazo de entrega al organismo "
                                                     f"{lic['plazo_entrega_dias']:g} días desde la OC del Estado.")
    st.session_state["oc_aviso"] = (f"Se cargaron {len(datos['items'])} ítems de {codigo}"
                                    + (f" (tienda {tienda})" if tienda else "") + " con su costo unitario neto.")


def _cargar_json() -> None:
    archivo = st.session_state.get("subir_oc")
    if not archivo:
        return
    try:
        datos = json.loads(archivo.getvalue().decode("utf-8"))
    except ValueError:
        st.session_state["oc_aviso"] = "El archivo no es un JSON válido."
        return
    comprador, proveedor = datos.get("comprador") or {}, datos.get("proveedor") or {}
    st.session_state["oc_numero"] = datos.get("numero") or st.session_state["oc_numero"]
    if datos.get("fecha"):
        st.session_state["oc_fecha"] = date.fromisoformat(datos["fecha"])
    st.session_state["oc_tipo"] = comprador.get("tipo", "persona_natural")
    for campos in CAMPOS_COMPRADOR.values():
        for _, campo in campos:
            st.session_state[f"oc_comp_{campo}"] = comprador.get(campo, "")
    for _, campo in PROVEEDOR:
        st.session_state[f"oc_prov_{campo}"] = proveedor.get(campo, "")
    for campo in ("licitacion", "oc_estado"):
        st.session_state[f"oc_ref_{campo}"] = (datos.get("referencia") or {}).get(campo, "")
    st.session_state["oc_descuento"] = datos.get("descuento") or 0
    for _, campo in CONDICIONES:
        valor = (datos.get("condiciones") or {}).get(campo)
        if campo == "fecha_entrega":
            st.session_state[f"oc_cond_{campo}"] = date.fromisoformat(valor) if valor else None
        else:
            st.session_state[f"oc_cond_{campo}"] = valor or ""
    _poner_items(datos.get("items") or [])
    st.session_state["oc_aviso"] = f"Se cargó la orden {datos.get('numero') or ''} desde el archivo."


def _items(df: pd.DataFrame) -> list[dict]:
    items = []
    for fila in df.to_dict("records"):
        item = {campo: fila[col] for campo, col in COLUMNAS.items() if pd.notna(fila.get(col)) and fila[col] != ""}
        if item:
            items.append(item)
    return items


def _datos() -> dict:
    ss = st.session_state
    tipo = ss["oc_tipo"]
    condiciones = {campo: ss[f"oc_cond_{campo}"] for _, campo in CONDICIONES}
    if isinstance(condiciones["fecha_entrega"], date):
        condiciones["fecha_entrega"] = condiciones["fecha_entrega"].isoformat()
    return {
        "numero": ss["oc_numero"], "fecha": ss["oc_fecha"].isoformat() if ss["oc_fecha"] else "",
        "comprador": {"tipo": tipo} | {campo: ss[f"oc_comp_{campo}"] for _, campo in CAMPOS_COMPRADOR[tipo]},
        "proveedor": {campo: ss[f"oc_prov_{campo}"] for _, campo in PROVEEDOR},
        "referencia": {"licitacion": ss["oc_ref_licitacion"], "oc_estado": ss["oc_ref_oc_estado"]},
        "items": _items(ss.get("oc_items_actual", ss["oc_items"])),
        "descuento": ss["oc_descuento"],
        "condiciones": condiciones,
    }


def _faltan_texto(faltan: list[str], tipo: str) -> list[str]:
    nombres = {f"comprador.{c}": f"Comprador: {e}" for e, c in CAMPOS_COMPRADOR[tipo]}
    nombres |= {f"proveedor.{c}": f"Proveedor: {e}" for e, c in PROVEEDOR}
    nombres |= {"numero": "Número de la orden", "fecha": "Fecha", "items": "Al menos un ítem"}
    texto = []
    for f in faltan:
        if f.startswith("items["):
            n, campo = f[6:].split("].")
            texto.append(f"Ítem {n}: {'precio (neto o con IVA)' if campo == 'precio' else campo}")
        else:
            texto.append(nombres.get(f, f))
    return texto


def pagina() -> None:
    _iniciar()
    pedido = st.session_state.pop("pedido_oc", None)
    if pedido:
        _cargar_licitacion(pedido, None)
    st.title("Orden de compra al proveedor")
    st.caption("La que le envías a la tienda o mayorista después de aceptar la OC del Estado. No se guarda nada "
               "en la plataforma: descarga el Excel (y los datos en JSON si quieres retomarla después).")
    if st.session_state.get("oc_aviso"):
        st.success(st.session_state.pop("oc_aviso"))

    with st.expander("Partir de una licitación o de una orden guardada", expanded=not st.session_state.get(
            "oc_ref_licitacion")):
        prep = comun.datos()
        lics = {l["codigo"]: l for l in prep["licitaciones"] if prep["items"].get(l["codigo"])}
        codigos = sorted(lics, key=lambda c: (c not in prep["mercado"], c))
        inicial = st.session_state.get("codigo")
        a, b, c = st.columns([3, 2, 1], vertical_alignment="bottom")
        codigo = a.selectbox("Licitación o Compra Ágil", codigos, index=codigos.index(inicial) if inicial in codigos else None,
                             format_func=lambda x: f"{x} · {(lics[x].get('nombre') or '')[:60]}",
                             placeholder="Elige una para traer sus ítems")
        tiendas = sorted({op.get("tienda") for op in prep["mercado"].get(codigo, []) if op.get("tienda")}) if codigo else []
        tienda = b.selectbox("Solo los ítems de", ["Todas las líneas"] + tiendas, disabled=not tiendas,
                             help="Si compras cada línea en una tienda distinta, haz una orden por tienda.")
        c.button("Cargar ítems", type="primary", disabled=not codigo, width="stretch", on_click=_cargar_licitacion,
                 args=(codigo, None if tienda == "Todas las líneas" else tienda))
        st.file_uploader("O sube una orden guardada (.json)", type="json", key="subir_oc", on_change=_cargar_json)

    st.subheader("Orden")
    a, b, c = st.columns(3)
    a.text_input("Número", key="oc_numero", help="La plataforma no guarda las órdenes: usa el correlativo que "
                 "sigue a tu última orden (o súbela en JSON arriba).")
    b.date_input("Fecha", key="oc_fecha", format="DD-MM-YYYY")
    c.radio("Compras como", list(TIPOS), format_func=TIPOS.get, key="oc_tipo", horizontal=True)

    izq, der = st.columns(2)
    with izq:
        st.markdown("**Comprador (tú)**")
        for etiqueta, campo in CAMPOS_COMPRADOR[st.session_state["oc_tipo"]]:
            st.text_input(etiqueta, key=f"oc_comp_{campo}")
        if not comun.secreto("comprador"):
            st.caption("Para no escribir tus datos cada vez, agrégalos a los secretos de la plataforma "
                       "(sección [comprador]; ver README).")
    with der:
        st.markdown("**Proveedor**")
        for etiqueta, campo in PROVEEDOR:
            st.text_input(etiqueta, key=f"oc_prov_{campo}")
        a, b = st.columns(2)
        a.text_input("Licitación", key="oc_ref_licitacion")
        b.text_input("N° OC del Estado", key="oc_ref_oc_estado", help="La orden que te envió el organismo")

    st.markdown("**Ítems** (precio neto o con IVA: basta uno)")
    version = st.session_state["oc_version"]
    if f"editor_oc_{version}" not in st.session_state:
        st.session_state["oc_items_actual"] = st.session_state["oc_items"]
    editado = st.data_editor(st.session_state["oc_items"], key=f"editor_oc_{version}", num_rows="dynamic",
                             hide_index=True, column_config={
                                 "Descripción": st.column_config.TextColumn(width="large", required=True),
                                 "Cantidad": st.column_config.NumberColumn(min_value=0, format="%g"),
                                 "Precio unitario neto": st.column_config.NumberColumn(min_value=0, format="localized"),
                                 "Precio unitario c/IVA": st.column_config.NumberColumn(min_value=0, format="localized"),
                             })
    st.session_state["oc_items_actual"] = editado

    st.markdown("**Condiciones**")
    a, b = st.columns(2)
    for k, (etiqueta, campo) in enumerate(CONDICIONES):
        col = a if k % 2 == 0 else b
        if campo == "fecha_entrega":
            col.date_input(etiqueta, key=f"oc_cond_{campo}", format="DD-MM-YYYY")
        else:
            col.text_input(etiqueta, key=f"oc_cond_{campo}")
    a.number_input("Descuento ($)", min_value=0, step=1000, key="oc_descuento")

    datos = _datos()
    t = totales(datos)
    k = st.columns(4)
    k[0].metric("Neto", comun.clp(t["neto"]))
    k[1].metric("IVA (19 %)", comun.clp(t["iva"]))
    k[2].metric("Total", comun.clp(t["total"]))
    k[3].metric("Ítems", len(datos["items"]))
    faltan = validar(datos)
    if faltan:
        st.warning("Falta completar (la orden se descarga igual, con esas celdas vacías): "
                   + "; ".join(_faltan_texto(faltan, datos["comprador"]["tipo"])) + ".")

    numero = datos["numero"] or "orden"
    a, b, c = st.columns(3)
    a.download_button("Descargar Excel", orden_xlsx(datos), f"{numero}.xlsx", icon="📥", type="primary", width="stretch",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    b.download_button("Guardar datos (.json)", json.dumps(datos, ensure_ascii=False, indent=2), f"{numero}.json",
                      "application/json", icon="💾", width="stretch",
                      help="Para retomarla después con «sube una orden guardada». Trae tus datos personales.")
    if shutil.which("soffice") or shutil.which("libreoffice"):
        if c.button("Preparar PDF", icon="🖨️", width="stretch"):
            st.session_state["oc_pdf"] = (numero, _pdf(datos))
        if st.session_state.get("oc_pdf", (None,))[0] == numero:
            c.download_button("Descargar PDF", st.session_state["oc_pdf"][1], f"{numero}.pdf", "application/pdf",
                              icon="📄", width="stretch")
    else:
        c.caption("PDF: abre el Excel y usa Archivo › Exportar como PDF.")


def _pdf(datos: dict) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        escritos = guardar(crear_orden(datos), Path(tmp) / "orden.xlsx", pdf=True)
        return escritos[1].read_bytes() if len(escritos) > 1 else None
