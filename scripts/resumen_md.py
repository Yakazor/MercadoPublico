"""Genera un resumen en Markdown del radar (para el resumen de GitHub Actions).

Uso:
    python scripts/resumen_md.py >> "$GITHUB_STEP_SUMMARY"
    python scripts/resumen_md.py --auditoria   # todas las filas, para revisar el filtro
"""
import sys

import pandas as pd

import _ruta  # noqa: F401
from radar.config import cargar_config, ruta_proyecto


def _fmt_monto(v, moneda=None):
    if pd.isna(v):
        return ""
    texto = f"{v:,.0f}".replace(",", ".")
    if moneda is None or pd.isna(moneda) or moneda == "CLP":
        return f"${texto}"
    return f"{texto} {moneda}"


def _fmt_dias(v):
    return "?" if pd.isna(v) else str(int(v))


def auditoria(df: pd.DataFrame) -> None:
    for rubro, g in df.sort_values(["rubro_nombre", "dias_restantes"]).groupby("rubro_nombre"):
        print(f"\n=== {rubro} ({len(g)}) ===")
        for _, f in g.iterrows():
            print(f"{f['codigo']} | {_fmt_dias(f['dias_restantes'])}d | "
                  f"{_fmt_monto(f['monto_estimado'], f.get('moneda')) or 's/m'} | "
                  f"[{f['palabras_detectadas']}] | {str(f['nombre'])[:90]} | {str(f['organismo'])[:45]}")


def main():
    config = cargar_config()
    carpeta = ruta_proyecto(config.get("rutas", {}).get("exportaciones", "data/exportaciones"))
    csv = carpeta / "licitaciones_actual.csv"
    if not csv.exists():
        print("No se generó el archivo de licitaciones.")
        return
    df = pd.read_csv(csv, sep=";", encoding="utf-8-sig")
    if "--auditoria" in sys.argv:
        auditoria(df)
        return
    print(f"## Radar de Licitaciones — {len(df)} vigentes en tus rubros\n")
    if df.empty:
        return
    print("| Rubro | Licitaciones | Monto estimado visible |")
    print("|---|---:|---:|")
    for rubro, g in df.groupby("rubro_nombre"):
        print(f"| {rubro} | {len(g)} | {_fmt_monto(g['monto_estimado'].sum(min_count=1))} |")

    print("\n### Cierran en los próximos 7 días\n")
    pronto = df[(df["dias_restantes"] >= 0) & (df["dias_restantes"] <= 7)].sort_values("dias_restantes")
    if pronto.empty:
        print("Ninguna.")
        return
    print("| Días | Código | Nombre | Organismo | Región | Monto |")
    print("|---:|---|---|---|---|---:|")
    for _, f in pronto.head(30).iterrows():
        nombre = str(f["nombre"])[:70].replace("|", "/")
        organismo = str(f["organismo"])[:40].replace("|", "/")
        region = f["region"] if pd.notna(f["region"]) else ""
        monto = _fmt_monto(f["monto_estimado"], f.get("moneda"))
        print(f"| {_fmt_dias(f['dias_restantes'])} | [{f['codigo']}]({f['url']}) | {nombre} | {organismo} | {region} | {monto} |")
    if len(pronto) > 30:
        print(f"\n…y {len(pronto) - 30} más en el Excel.")


if __name__ == "__main__":
    sys.exit(main())
