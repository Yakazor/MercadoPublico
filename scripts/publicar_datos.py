"""Exporta los datos del radar en JSON para el dashboard (rama `datos` del repo).

Uso:
    python scripts/publicar_datos.py --salida /tmp/datos

Genera:
    licitaciones.json  licitaciones vigentes de tus rubros (una fila por licitación) y
                       Compras Ágiles abiertas (tipo "Compra Ágil", de scripts/compra_agil.py)
    precios.json       precios adjudicados en OC por producto (resumen_precios)
    items.json         ítems de cada licitación vigente (cantidad, unidad y precio de
                       referencia en OC), para el simulador de presupuesto
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
from radar.presupuesto import ReferenciasOC, items_licitacion_presupuesto

COLUMNAS_LICITACIONES = [
    "codigo", "nombre", "organismo", "region", "comuna", "monto_estimado", "moneda", "tipo", "rubro",
    "fecha_publicacion", "fecha_cierre", "dias_restantes", "estado", "rubro_nombre",
    "palabras_detectadas", "alertas_regulatorias", "solo_regulados", "url", "primera_deteccion",
    "llamado", "plazo_entrega_dias", "direccion_entrega",
]
MAX_PRECIOS = 3000  # productos con más monto adjudicado (el archivo queda bajo ~1 MB)


def compras_agiles(ruta: Path, hoy) -> dict | None:
    """Resultado de scripts/compra_agil.py si es de hoy (uno antiguo mostraría compras ya cerradas)."""
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return datos if datos.get("fecha") == hoy.isoformat() else None


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
        detalles = {codigo: guardado[0] for codigo in vigentes["codigo"]
                    if (guardado := db.detalle_licitacion(codigo))}
    finally:
        db.cerrar()
    agiles = compras_agiles(ruta_proyecto(config.get("rutas", {}).get("compras_agiles", "data/compras_agiles.json")), hoy)
    if agiles and agiles.get("filas"):
        filas_ca = pd.DataFrame(agiles["filas"]).reindex(columns=COLUMNAS_LICITACIONES)
        filas_ca = filas_ca[~filas_ca["codigo"].isin(vigentes["codigo"])]
        vigentes = pd.concat([vigentes, filas_ca], ignore_index=True)
        vigentes["llamado"] = pd.to_numeric(vigentes["llamado"], errors="coerce").astype("Int64")
        detalles |= agiles.get("detalles") or {}

    claves = {datos.get("nombre", clave): clave for clave, datos in (config.get("rubros") or {}).items()}
    precios.insert(0, "rubro", precios["rubro_nombre"].map(claves))
    # Referencia de precio para cada ítem: con todos los productos, no solo los publicados.
    referencias = ReferenciasOC(precios)
    items = [fila for lic in vigentes[["codigo", "rubro"]].itertuples(index=False) if lic.codigo in detalles
             for fila in items_licitacion_presupuesto(lic.codigo, lic.rubro, detalles[lic.codigo], referencias)]
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
        "licitaciones": int((vigentes["tipo"] != "Compra Ágil").sum()),
        "compras_agiles": len(agiles["filas"]) if agiles else None,
        "compras_agiles_generado": agiles.get("generado") if agiles else None,
        "productos_con_precio": len(precios),
        "items": len(items),
        "oc_desde": dias[0] if dias else None,
        "oc_hasta": dias[-1] if dias else None,
        "oc_dias": len(dias),
    }
    for nombre, datos in (("licitaciones.json", _filas(vigentes)), ("precios.json", _filas(precios)),
                          ("items.json", items), ("meta.json", [meta])):
        (salida / nombre).write_text(json.dumps(datos, ensure_ascii=False, indent=None), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
