"""Arma presupuestos de licitaciones con los precios de mercado encontrados.

Uso:
    python scripts/presupuesto.py --items items.json --licitaciones licitaciones.json

Lee:
    items.json, licitaciones.json   de la rama `datos` (los publica el radar)
    informes/mercado/<codigo>.json  precios de mercado buscados para esa licitación
                                    (tienda, producto, link, precio y fecha de consulta)
Escribe:
    informes/presupuestos/<codigo>.md y .csv   presupuesto por licitación
    informes/README.md                          índice de presupuestos
    --mercado-json <ruta>                       (opcional) todas las opciones en una
                                                tabla, para el dashboard

Supuestos (se pueden cambiar con --margen y --otros-costos): precios de mercado
convertidos a neto (sin IVA) y a la unidad que pide la licitación; oferta = costo
neto × (1 + otros costos) × (1 + margen); IVA 19 % sobre la oferta.
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
    """Opciones de cada ítem como filas (una por tienda)."""
    filas = []
    for item in mercado.get("items") or []:
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
                "fecha_consulta": op.get("fecha_consulta") or mercado.get("fecha_consulta"),
                "nota": op.get("nota"),
            })
    return filas


def markdown(lic: dict, mercado: dict, p: dict) -> str:
    codigo = lic.get("codigo") or mercado.get("codigo")
    lineas = [
        f"# Presupuesto: {_celda(lic.get('nombre'))}",
        "",
        f"- **Licitación:** [{codigo}]({URL_LICITACION.format(codigo)})",
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
        lineas.append(
            f"| {it.get('linea')} | {producto} | {cant} | {_clp(it.get('costo_unitario_neto'))} | "
            f"{_link(it.get('tienda'), it.get('url')) if it.get('tienda') else '—'} | {_clp(it.get('subtotal_costo'))} | "
            f"{_clp(it.get('oferta_unitaria_neta'))} | {_clp(it.get('subtotal_oferta'))} | {_clp(it.get('ref_mediana'))} |")
    otras = [op for op in opciones_mercado(mercado)]
    if otras:
        lineas += ["", "## Todas las opciones encontradas", "",
                   "| Línea | Tienda | Producto en la tienda | Precio publicado | Neto por unidad pedida | Coincidencia | Verificado |",
                   "|---:|---|---|---:|---:|---|---|"]
        for op in sorted(otras, key=lambda o: (o["linea"] or 0, o["precio_unitario_neto"] or float("inf"))):
            iva = " (c/IVA)" if op.get("iva_incluido") else (" (+IVA)" if op.get("iva_incluido") is False else "")
            lineas.append(
                f"| {op['linea']} | {_link(op.get('tienda'), op.get('url'))} | {_celda(op.get('producto_mercado'))[:100]} | "
                f"{_clp(op.get('precio'))}{iva} | {_clp(op.get('precio_unitario_neto'))} | {_celda(op.get('coincidencia'))} | "
                f"{'sí' if op.get('verificado') else 'no'} |")
    notas = [f"- Línea {i.get('linea')}: {_celda(i.get('nota'))}" for i in mercado.get("items") or [] if i.get("nota")]
    if notas:
        lineas += ["", "## Notas de la búsqueda", "", *notas]
    lineas += ["", "_Generado con `scripts/presupuesto.py`. Los precios de mercado son una foto de la fecha de "
                   "consulta: revisa stock, despacho a la región y condiciones de la licitación antes de ofertar._", ""]
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
        # Punto y coma y coma decimal: Excel en español lo abre bien.
        tabla.to_csv(salida / f"{codigo}.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
        resumen.append((lic, mercado, p, codigo in lics))

    lineas = [
        "# Informes",
        "",
        "Presupuestos de licitaciones con precios del mercado chileno (tiendas con link) y el precio que el",
        "Estado ya pagó en órdenes de compra. Se generan con `scripts/presupuesto.py`; los precios de mercado",
        "están en `informes/mercado/` con su fecha de consulta.",
        "",
        f"Actualizado: {date.today().isoformat()}. Margen {_pct(args.margen)}, otros costos "
        f"{_pct(args.otros_costos)}, IVA {_pct(IVA)}.",
        "",
        "| Licitación | Rubro | Cierre | Ítems con precio | Costo neto | Oferta total (c/IVA) | Utilidad | Monto estimado |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for lic, mercado, p, vigente in sorted(resumen, key=lambda r: r[0].get("fecha_cierre") or ""):
        codigo = lic.get("codigo")
        n = len(p["items"])
        estado = "" if vigente else " (ya no vigente)"
        lineas.append(
            f"| [{codigo}](presupuestos/{codigo}.md) {_celda(lic.get('nombre'))[:70]}{estado} | {_celda(lic.get('rubro_nombre'))} | "
            f"{(lic.get('fecha_cierre') or '—')[:10]} | {n - p['items_sin_precio']}/{n} | {_clp(p['costo_neto'])} | "
            f"{_clp(p['oferta_total'])} | {_clp(p['utilidad'])} | "
            f"{_clp(lic.get('monto_estimado')) if lic.get('moneda') in (None, 'CLP') else '—'} |")
    lineas.append("")
    Path(args.indice).write_text("\n".join(lineas), encoding="utf-8")
    if args.mercado_json:
        Path(args.mercado_json).write_text(json.dumps(todas, ensure_ascii=False), encoding="utf-8")
    print(f"{len(resumen)} presupuestos en {salida}")


if __name__ == "__main__":
    main()
