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


def _es_clp(moneda) -> bool:
    return moneda is None or pd.isna(moneda) or str(moneda).strip().upper() in ("", "CLP", "PESO", "$")


def _monto(v, moneda=None) -> str:
    """CLP sin decimales; UF/USD/otras con 2 decimales y su código."""
    if pd.isna(v):
        return ""
    if _es_clp(moneda):
        return f"{v:,.0f}".replace(",", ".")
    texto = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{texto} {moneda}"


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

    # Primero CLP (comparables entre sí); dentro de cada moneda, por monto total.
    resumen = resumen.assign(_no_clp=~resumen["moneda"].map(_es_clp))
    nota = "⚠ = producto con registro/certificación obligatoria (ver columna alertas_regulatorias del Excel)"
    print(nota if args.texto else f"_{nota}_")

    for rubro, g in resumen.groupby("rubro_nombre"):
        # Top N dentro de cada moneda (CLP primero): los montos en UF/USD no se
        # comparan con pesos ni quedan ocultos detrás de ellos.
        g = (g.sort_values(["_no_clp", "moneda", "monto_total"], ascending=[True, True, False])
              .groupby("moneda", dropna=False, sort=False).head(args.top))
        if args.texto:
            print(f"\n=== {rubro} (top {args.top} por moneda; CLP primero) ===")
            for _, f in g.iterrows():
                m = f["moneda"]
                unidad = f["unidad"] if pd.notna(f["unidad"]) else "s/u"
                alerta = "⚠ " if pd.notna(f["alertas_regulatorias"]) else "  "
                print(f"{alerta}{str(f['producto_normalizado'])[:55]:55} | {unidad:10} | OC={f['n_ordenes']:>3} "
                      f"prov={f['n_proveedores']:>3} | mediana {_monto(f['precio_mediana'], m)} "
                      f"(p25 {_monto(f['precio_p25'], m)} – p75 {_monto(f['precio_p75'], m)}; "
                      f"mín {_monto(f['precio_min'], m)} máx {_monto(f['precio_max'], m)}) | "
                      f"total {_monto(f['monto_total'], m)}")
        else:
            print(f"\n### {rubro}\n")
            print("| | Producto | Unidad | Moneda | OC | Proveedores | Mediana | P25 – P75 | Monto total |")
            print("|---|---|---|---|---:|---:|---:|---:|---:|")
            for _, f in g.iterrows():
                m = f["moneda"]
                unidad = f["unidad"] if pd.notna(f["unidad"]) else ""
                alerta = "⚠" if pd.notna(f["alertas_regulatorias"]) else ""
                producto = str(f["producto_normalizado"])[:60].replace("|", "/")
                print(f"| {alerta} | {producto} | {unidad} | {m if pd.notna(m) else ''} | {f['n_ordenes']} | "
                      f"{f['n_proveedores']} | {_monto(f['precio_mediana'], m)} | "
                      f"{_monto(f['precio_p25'], m)} – {_monto(f['precio_p75'], m)} | {_monto(f['monto_total'], m)} |")


if __name__ == "__main__":
    main()
