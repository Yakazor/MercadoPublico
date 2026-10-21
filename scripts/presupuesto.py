"""Arma presupuestos de licitaciones con los precios de mercado encontrados.

Uso:
    python scripts/presupuesto.py --items items.json --licitaciones licitaciones.json

Lee:
    items.json, licitaciones.json   de la rama `datos` (los publica el radar)
    informes/mercado/<codigo>.json  precios de mercado buscados para esa licitación
                                    (tienda, producto, link, precio y fecha de consulta)
Escribe:
    informes/presupuestos/<codigo>.md y .csv   presupuesto por licitación
    informes/README.md                          índice de presupuestos (vigentes con
                                                alertas; las ya cerradas al final)
    --mercado-json <ruta>                       (opcional) todas las opciones no
                                                descartadas en una tabla, para el dashboard

Supuestos (se pueden cambiar con --margen y --otros-costos): precios de mercado
convertidos a neto (sin IVA) y a la unidad que pide la licitación; oferta = costo
neto × (1 + otros costos) × (1 + margen); IVA 19 % sobre la oferta. Las opciones
con "descartado": true (y su "motivo_descarte") se muestran, pero no se usan.
"""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

import _ruta  # noqa: F401
from radar.config import ruta_proyecto
from radar.presupuesto import IVA, armar_presupuesto

URL_LICITACION = "https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion={}"


def _clp(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return "$" + f"{round(valor):,}".replace(",", ".")


def _pct(valor) -> str:
    return "—" if valor is None or pd.isna(valor) else f"{valor * 100:.0f} %".replace(".", ",")


def _celda(texto) -> str:
    """Texto seguro dentro de una tabla Markdown."""
    return " ".join(str(texto or "").replace("|", "/").split())


def _link(texto, url) -> str:
    texto = _celda(texto) or "ver"
    return f"[{texto}]({url})" if url and str(url).startswith("https://") else texto


def opciones_mercado(mercado: dict) -> list[dict]:
    """Opciones de cada ítem como filas (una por tienda), con las descartadas marcadas."""
    filas = []
    for item in mercado.get("items") or []:
        # La clave numera todas las opciones (también las descartadas): no cambia al descartar una.
        for n, op in enumerate(item.get("opciones") or [], 1):
            filas.append({
                "clave": f"{mercado.get('codigo')}|{item.get('linea')}|{n}",
                "codigo": mercado.get("codigo"),
                "linea": item.get("linea"),
                "opcion": n,
                "tienda": op.get("tienda"),
                "producto_mercado": op.get("producto_mercado"),
                "url": op.get("url"),
                "precio": op.get("precio"),
                "iva_incluido": op.get("iva_incluido"),
                "unidades_equivalentes": op.get("unidades_equivalentes"),
                "precio_unitario_neto": op.get("precio_unitario_neto"),
                "coincidencia": op.get("coincidencia"),
                "verificado": op.get("verificado"),
                "verificado_en": op.get("verificado_en"),
                "verificacion_pagina": op.get("verificacion_pagina"),
                "fecha_consulta": op.get("fecha_consulta") or mercado.get("fecha_consulta"),
                "nota": op.get("nota"),
                "descartado": bool(op.get("descartado")),
                "motivo_descarte": op.get("motivo_descarte"),
            })
    return filas


def opciones_dashboard(opciones: list[dict]) -> list[dict]:
    """Opciones para el dashboard: sin las descartadas, porque el dashboard no conoce el
    campo y las usaría como mejor precio."""
    return [{k: v for k, v in op.items() if k not in ("descartado", "motivo_descarte")}
            for op in opciones if not op.get("descartado")]


def _verificado(op: dict) -> str:
    """«sí (fecha)» si la página de la tienda mostró el precio; si no, por qué no.
    Las descartadas por la auditoría dicen «descartada: <motivo>»."""
    if op.get("descartado"):
        motivo = _celda(op.get("motivo_descarte"))
        return f"descartada: {motivo}" if motivo else "descartada"
    if op.get("verificado"):
        return f"sí ({op.get('verificado_en')})" if op.get("verificado_en") else "sí"
    motivo = op.get("verificacion_pagina")
    if not motivo:
        return "no (aún no se abre la página)"
    return "no: " + _celda(motivo.split(": ", 1)[-1])


def _supera_monto(lic: dict, p: dict) -> bool:
    monto = lic.get("monto_estimado")
    return bool(monto) and lic.get("moneda") in (None, "CLP") and p["oferta_total"] > monto


def _lineas(numeros: list) -> str:
    """«la línea 3» o «las líneas 1, 4 y 7»."""
    numeros = [str(n) for n in numeros]
    if len(numeros) == 1:
        return f"la línea {numeros[0]}"
    return f"las líneas {', '.join(numeros[:-1])} y {numeros[-1]}"


def alertas(lic: dict, p: dict) -> list[str]:
    """Avisos cortos para el índice: lo que hay que revisar antes de creer en el total."""
    avisos = []
    if _supera_monto(lic, p):
        avisos.append("supera monto")
    n = p["items_sin_precio"]
    if n:
        avisos.append("falta 1 precio" if n == 1 else f"faltan {n} precios")
    if p.get("lineas_globales"):
        avisos.append("línea global")
    if p.get("items_sin_verificar"):
        avisos.append("sin verificar")
    return avisos


def markdown(lic: dict, mercado: dict, p: dict) -> str:
    codigo = lic.get("codigo") or mercado.get("codigo")
    agil = lic.get("tipo") == "Compra Ágil" or str(codigo).endswith(("-COT25", "-COT26", "-COT27"))
    lineas = [
        f"# Presupuesto: {_celda(lic.get('nombre'))}",
        "",
        # Compra Ágil no tiene ficha con enlace estable: se busca por código en Mercado Público.
        f"- **Compra Ágil:** {codigo} (búscala por código en Mercado Público; se cotiza el TOTAL con IVA y despacho)"
        if agil else f"- **Licitación:** [{codigo}]({URL_LICITACION.format(codigo)})",
        f"- **Organismo:** {_celda(lic.get('organismo'))} ({_celda(lic.get('region'))})",
        f"- **Cierre:** {lic.get('fecha_cierre') or '—'} · **Monto estimado:** "
        f"{_clp(lic.get('monto_estimado')) if lic.get('moneda') in (None, 'CLP') else str(lic.get('monto_estimado')) + ' ' + str(lic.get('moneda'))}",
        f"- **Rubro:** {_celda(lic.get('rubro_nombre'))}",
        f"- **Precios de mercado consultados:** {mercado.get('fecha_consulta') or '—'} (pueden cambiar; confírmalos antes de ofertar)",
        f"- **Supuestos:** precios netos (sin IVA) por unidad pedida; otros costos {_pct(p['otros_costos'])} "
        f"(despacho, garantías); margen {_pct(p['margen'])}; IVA {_pct(IVA)}.",
        "",
        "## Resumen",
        "",
        "| Concepto | Monto |",
        "|---|---:|",
        f"| Costo de compra con otros costos (neto) | {_clp(p['costo_neto'])} |",
        f"| Oferta sugerida (neto) | {_clp(p['oferta_neta'])} |",
        f"| IVA | {_clp(p['oferta_iva'])} |",
        f"| **Oferta total** | **{_clp(p['oferta_total'])}** |",
        f"| Utilidad estimada | {_clp(p['utilidad'])} |",
        f"| Lo que el Estado pagó en OC por esos ítems (mediana, neto) | {_clp(p['referencia_oc_neta'])} |",
        "",
    ]
    if p["items_sin_precio"]:
        lineas += [f"> {p['items_sin_precio']} ítem(s) sin precio de mercado: no entran en los totales.", ""]
    if p.get("oferta_con_referencia") and p.get("referencia_oc_neta") and p["oferta_con_referencia"] > p["referencia_oc_neta"]:
        lineas += [f"> Ojo: en los ítems con referencia, la oferta ({_clp(p['oferta_con_referencia'])}) supera lo que "
                   f"el Estado pagó en OC ({_clp(p['referencia_oc_neta'])}). Revisa el margen o busca proveedores más baratos.", ""]
    if _supera_monto(lic, p):
        lineas += [f"> La oferta total supera el monto estimado de la licitación ({_clp(lic['monto_estimado'])}).", ""]
    if p.get("lineas_globales"):
        unidades = {it.get("linea"): _celda(it.get("unidad")) for it in p["items"]}
        detalle = [f"{n} ({unidades.get(n)})" for n in p["lineas_globales"]]
        lineas += [f"> Unidad global en {_lineas(detalle)}: la cantidad real está en las bases de la "
                   "licitación, así que su total puede no ser comparable.", ""]
    no_comparables = [it.get("linea") for it in p["items"] if it.get("referencia_comparable") is False]
    if no_comparables:
        lineas += [f"> Ref. OC «no comparable» en {_lineas(no_comparables)}: la mediana de OC difiere más de "
                   "10 veces del costo unitario (probablemente otra presentación) y no entra en lo que pagó el Estado.", ""]
    lineas += [
        "## Ítems",
        "",
        "| Línea | Producto | Cantidad | Mejor precio neto / unidad | Tienda | Subtotal costo | Oferta / unidad | Subtotal oferta | Ref. OC (mediana) |",
        "|---:|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for it in p["items"]:
        cantidad = it.get("cantidad")
        cant = f"{cantidad:g} {_celda(it.get('unidad'))}".strip() if cantidad is not None else "—"
        producto = _celda(it.get("producto"))
        if it.get("descripcion"):
            producto += f" — {_celda(it['descripcion'])[:120]}"
        ref = _clp(it.get("ref_mediana"))
        if it.get("referencia_comparable") is False:
            ref += " (no comparable)"
        lineas.append(
            f"| {it.get('linea')} | {producto} | {cant} | {_clp(it.get('costo_unitario_neto'))} | "
            f"{_link(it.get('tienda'), it.get('url')) if it.get('tienda') else '—'} | {_clp(it.get('subtotal_costo'))} | "
            f"{_clp(it.get('oferta_unitaria_neta'))} | {_clp(it.get('subtotal_oferta'))} | {ref} |")
    otras = [op for op in opciones_mercado(mercado)]
    if otras:
        lineas += ["", "## Todas las opciones encontradas", "",
                   "| Línea | Tienda | Producto en la tienda | Precio publicado | Neto por unidad pedida | Coincidencia | Verificado |",
                   "|---:|---|---|---:|---:|---|---|"]
        # Las descartadas, al final de su línea.
        for op in sorted(otras, key=lambda o: (o["linea"] or 0, o["descartado"], o["precio_unitario_neto"] or float("inf"))):
            iva = " (c/IVA)" if op.get("iva_incluido") else (" (+IVA)" if op.get("iva_incluido") is False else "")
            lineas.append(
                f"| {op['linea']} | {_link(op.get('tienda'), op.get('url'))} | {_celda(op.get('producto_mercado'))[:100]} | "
                f"{_clp(op.get('precio'))}{iva} | {_clp(op.get('precio_unitario_neto'))} | {_celda(op.get('coincidencia'))} | "
                f"{_verificado(op)} |")
    notas = [f"- Línea {i.get('linea')}: {_celda(i.get('nota'))}" for i in mercado.get("items") or [] if i.get("nota")]
    if notas:
        lineas += ["", "## Notas de la búsqueda", "", *notas]
    lineas += ["", "_Generado con `scripts/presupuesto.py`. Los precios de mercado son una foto de la fecha de "
                   "consulta: revisa stock, despacho a la región y condiciones de la licitación antes de ofertar._", ""]
    return "\n".join(lineas)


def indice(resumen: list[tuple], margen: float, otros_costos: float) -> str:
    """Índice de presupuestos. `resumen`: (licitación, mercado, presupuesto, vigente).
    Vigentes = las que siguen en licitaciones.json; las demás van en «Ya cerradas»."""
    vigentes = sorted((r for r in resumen if r[3]), key=lambda r: r[0].get("fecha_cierre") or "")
    cerradas = sorted((r for r in resumen if not r[3]), key=lambda r: r[0].get("codigo") or "")
    lineas = [
        "# Informes",
        "",
        "Presupuestos de licitaciones con precios del mercado chileno (tiendas con link) y el precio que el",
        "Estado ya pagó en órdenes de compra. Se generan con `scripts/presupuesto.py`; los precios de mercado",
        "están en `informes/mercado/` con su fecha de consulta.",
        "",
        "- [Guía de uso y de postulación a Mercado Público (PDF)](Guia_Radar_Licitaciones.pdf)",
        "- [Grupos de licitaciones: todos los segmentos vs los rubros del radar](grupos_licitaciones.md)",
        "- [Versiones en PDF de los informes](pdf/)",
        "",
        f"Actualizado: {date.today().isoformat()}. Margen {_pct(margen)}, otros costos "
        f"{_pct(otros_costos)}, IVA {_pct(IVA)}.",
        "",
        "## Licitaciones vigentes",
        "",
        # Una sola línea: informes_pdf.py convierte cada línea en un párrafo.
        "Alertas: «supera monto» (la oferta total pasa el monto estimado), «faltan N precios» (ítems sin precio "
        "de mercado, fuera de los totales), «línea global» (unidad Global, Kit, Servicio o Lote: la cantidad real "
        "está en las bases) y «sin verificar» (algún precio usado no se confirmó en la página de la tienda).",
        "",
        "| Licitación | Rubro | Cierre | Ítems con precio | Costo neto | Oferta total (c/IVA) | Utilidad | Monto estimado | Alertas |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for lic, mercado, p, _ in vigentes:
        codigo = lic.get("codigo")
        n = len(p["items"])
        lineas.append(
            f"| [{codigo}](presupuestos/{codigo}.md) {_celda(lic.get('nombre'))[:70]} | {_celda(lic.get('rubro_nombre'))} | "
            f"{(lic.get('fecha_cierre') or '—')[:10]} | {n - p['items_sin_precio']}/{n} | {_clp(p['costo_neto'])} | "
            f"{_clp(p['oferta_total'])} | {_clp(p['utilidad'])} | "
            f"{_clp(lic.get('monto_estimado')) if lic.get('moneda') in (None, 'CLP') else '—'} | "
            f"{', '.join(alertas(lic, p)) or '—'} |")
    if cerradas:
        lineas += ["", "## Ya cerradas", ""]
        lineas += [f"- [{lic.get('codigo')}](presupuestos/{lic.get('codigo')}.md) {_celda(lic.get('nombre'))}"
                   for lic, *_ in cerradas]
    lineas.append("")
    return "\n".join(lineas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", required=True, help="items.json de la rama datos")
    ap.add_argument("--licitaciones", required=True, help="licitaciones.json de la rama datos")
    ap.add_argument("--mercado", default=str(ruta_proyecto("informes/mercado")))
    ap.add_argument("--salida", default=str(ruta_proyecto("informes/presupuestos")))
    ap.add_argument("--indice", default=str(ruta_proyecto("informes/README.md")))
    ap.add_argument("--mercado-json", help="escribe todas las opciones en una tabla JSON (dashboard)")
    ap.add_argument("--margen", type=float, default=0.20)
    ap.add_argument("--otros-costos", type=float, default=0.05)
    args = ap.parse_args()

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    lics = {l["codigo"]: l for l in json.loads(Path(args.licitaciones).read_text(encoding="utf-8"))}
    por_codigo: dict[str, list[dict]] = {}
    for it in items:
        por_codigo.setdefault(it["codigo"], []).append(it)

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    resumen, todas = [], []
    for archivo in sorted(Path(args.mercado).glob("*.json")):
        mercado = json.loads(archivo.read_text(encoding="utf-8"))
        codigo = mercado.get("codigo") or archivo.stem
        opciones = opciones_mercado(mercado)
        todas += opciones
        lic = lics.get(codigo) or {"codigo": codigo, "nombre": mercado.get("nombre")}
        p = armar_presupuesto(por_codigo.get(codigo, []), opciones, args.margen, args.otros_costos)
        (salida / f"{codigo}.md").write_text(markdown(lic, mercado, p), encoding="utf-8")
        tabla = pd.DataFrame(p["items"])
        dinero = ["ref_mediana", "ref_p25", "costo_unitario_neto", "oferta_unitaria_neta", "subtotal_costo", "subtotal_oferta"]
        # Columnas sin ningún valor (todo None) quedan como object: se pasan a número antes de redondear.
        for col, decimales in [(c, 0) for c in dinero] + [("margen_vs_referencia", 3)]:
            if col in tabla:
                tabla[col] = pd.to_numeric(tabla[col], errors="coerce").round(decimales)
        # Punto y coma y coma decimal: Excel en español lo abre bien.
        tabla.to_csv(salida / f"{codigo}.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
        resumen.append((lic, mercado, p, codigo in lics))

    Path(args.indice).write_text(indice(resumen, args.margen, args.otros_costos), encoding="utf-8")
    if args.mercado_json:
        Path(args.mercado_json).write_text(json.dumps(opciones_dashboard(todas), ensure_ascii=False), encoding="utf-8")
    print(f"{len(resumen)} presupuestos en {salida}")


if __name__ == "__main__":
    main()
