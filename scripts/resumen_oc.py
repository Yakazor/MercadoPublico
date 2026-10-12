"""Resumen legible de precios adjudicados en órdenes de compra (para logs y GitHub).

Uso:
    python scripts/resumen_oc.py                  # tabla Markdown (resumen de Actions)
    python scripts/resumen_oc.py --texto          # texto plano para revisar en el log
    python scripts/resumen_oc.py --top 25         # productos por rubro (por defecto 15)
"""
import argparse

import pandas as pd

import _ruta  # noqa: F401
from radar.almacenamiento import BaseDatos
from radar.config import cargar_config, ruta_proyecto
from radar.ordenes_compra import resumen_precios


def _clp(v) -> str:
    return "" if pd.isna(v) else f"{v:,.0f}".replace(",", ".")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--texto", action="store_true")
    p.add_argument("--top", type=int, default=15)
    args = p.parse_args()

    config = cargar_config()
    db = BaseDatos(ruta_proyecto(config.get("rutas", {}).get("base_datos", "data/radar.db")))
    try:
        items = db.items_oc()
        dias = [d for (d,) in db.con.execute("SELECT fecha FROM ordenes_compra_dias ORDER BY fecha")]
    finally:
        db.cerrar()

    rango = f"{dias[0]} a {dias[-1]} ({len(dias)} días)" if dias else "sin días procesados"
    n_oc = items["codigo_oc"].nunique() if not items.empty else 0
    titulo = f"Precios adjudicados en OC — {rango}: {len(items)} ítems de {n_oc} órdenes"
    print(titulo if args.texto else f"## {titulo}\n")

    resumen = resumen_precios(items)
    if resumen.empty:
        print("Sin ítems con precio todavía.")
        return

    for rubro, g in resumen.groupby("rubro_nombre"):
        g = g.sort_values("monto_total", ascending=False).head(args.top)
        if args.texto:
            print(f"\n=== {rubro} (top {len(g)} por monto) ===")
            for _, f in g.iterrows():
                unidad = f["unidad"] if pd.notna(f["unidad"]) else "s/u"
                moneda = "" if f["moneda"] in (None, "CLP") or pd.isna(f["moneda"]) else f" {f['moneda']}"
                print(f"{str(f['producto_normalizado'])[:55]:55} | {unidad:10} | OC={f['n_ordenes']:>3} "
                      f"prov={f['n_proveedores']:>3} | mediana {_clp(f['precio_mediana'])}{moneda} "
                      f"(p25 {_clp(f['precio_p25'])} – p75 {_clp(f['precio_p75'])}; "
                      f"mín {_clp(f['precio_min'])} máx {_clp(f['precio_max'])}) | total {_clp(f['monto_total'])}")
        else:
            print(f"\n### {rubro}\n")
            print("| Producto | Unidad | OC | Proveedores | Mediana | P25 – P75 | Monto total |")
            print("|---|---|---:|---:|---:|---:|---:|")
            for _, f in g.iterrows():
                unidad = f["unidad"] if pd.notna(f["unidad"]) else ""
                print(f"| {str(f['producto_normalizado'])[:60]} | {unidad} | {f['n_ordenes']} | "
                      f"{f['n_proveedores']} | {_clp(f['precio_mediana'])} | "
                      f"{_clp(f['precio_p25'])} – {_clp(f['precio_p75'])} | {_clp(f['monto_total'])} |")


if __name__ == "__main__":
    main()
