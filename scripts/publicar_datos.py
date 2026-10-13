"""Exporta los datos del radar en JSON para el dashboard (rama `datos` del repo).

Uso:
    python scripts/publicar_datos.py --salida /tmp/datos

Genera:
    licitaciones.json  licitaciones vigentes de tus rubros (una fila por licitación)
    precios.json       precios adjudicados en OC por producto (resumen_precios)
    meta.json          fecha de generación y rango de días de OC procesados
"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import _ruta  # noqa: F401
from radar.almacenamiento import BaseDatos
from radar.config import cargar_config, hoy_chile, ruta_proyecto
from radar.filtro import FiltroRubros
from radar.ordenes_compra import reclasificar_items, resumen_precios

COLUMNAS_LICITACIONES = [
    "codigo", "nombre", "organismo", "region", "comuna", "monto_estimado", "moneda", "tipo", "rubro",
    "fecha_publicacion", "fecha_cierre", "dias_restantes", "estado", "rubro_nombre",
    "palabras_detectadas", "alertas_regulatorias", "solo_regulados", "url", "primera_deteccion",
]
MAX_PRECIOS = 3000  # productos con más monto adjudicado (el archivo queda bajo ~1 MB)


def _filas(df: pd.DataFrame) -> list[dict]:
    """Filas JSON: NaN → null, enteros de pandas → int."""
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", required=True, help="carpeta donde escribir los JSON")
    args = p.parse_args()

    config = cargar_config()
    db = BaseDatos(ruta_proyecto(config.get("rutas", {}).get("base_datos", "data/radar.db")))
    try:
        hoy = hoy_chile()
        # Precios con la config.yaml vigente aunque el último workflow de OC sea anterior
        # (no llama a la API; en Actions corre después de guardar la base).
        reclasificar_items(db, FiltroRubros.desde_config(config))
        vigentes = db.licitaciones_vigentes(hoy=hoy).reindex(columns=COLUMNAS_LICITACIONES)
        precios = resumen_precios(db.items_oc())
        dias = [d for (d,) in db.con.execute("SELECT fecha FROM ordenes_compra_dias ORDER BY fecha")]
    finally:
        db.cerrar()

    precios = precios.sort_values("monto_total", ascending=False).head(MAX_PRECIOS)
    # Clave estable de cada fila para el dashboard (no cambia con el orden por monto).
    precios.insert(0, "id", [
        hashlib.sha1("|".join(str(v) for v in clave).encode()).hexdigest()[:12]
        for clave in precios[["rubro_nombre", "producto_normalizado", "unidad", "moneda"]].itertuples(index=False)
    ])
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    meta = {
        "generado": datetime.now(ZoneInfo("America/Santiago")).isoformat(timespec="seconds"),
        "fecha": hoy.isoformat(),
        "licitaciones": len(vigentes),
        "productos_con_precio": len(precios),
        "oc_desde": dias[0] if dias else None,
        "oc_hasta": dias[-1] if dias else None,
        "oc_dias": len(dias),
    }
    for nombre, datos in (("licitaciones.json", _filas(vigentes)), ("precios.json", _filas(precios)),
                          ("meta.json", [meta])):
        (salida / nombre).write_text(json.dumps(datos, ensure_ascii=False, indent=None), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
