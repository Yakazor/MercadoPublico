"""Guarda los precios de mercado buscados en informes/mercado/<codigo>.json.

Uso:
    python scripts/guardar_mercado.py resultado.json

`resultado.json` es lo que devuelve el workflow `.claude/workflows/precios-mercado-chile.js`:
{"licitaciones": [{"codigo", "nombre", "fecha_consulta", "verificacion", "items": [...]}]}
(también acepta directamente la lista). Cada opción queda con su fecha de consulta y
con precio_unitario_neto recalculado (precio / 1,19 si incluye IVA / unidades
equivalentes), para que el presupuesto no dependa de la aritmética de la búsqueda.
"""
import json
import sys
from pathlib import Path

import _ruta  # noqa: F401
from radar.config import ruta_proyecto
from radar.presupuesto import IVA


def neto_por_unidad(op: dict) -> float | None:
    try:
        precio = float(op["precio"])
        unidades = float(op.get("unidades_equivalentes") or 1)
    except (KeyError, TypeError, ValueError):
        return None
    if precio <= 0 or unidades <= 0:
        return None
    neto = precio / (1 + IVA) if op.get("iva_incluido", True) else precio
    return round(neto / unidades, 2)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    datos = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    licitaciones = datos.get("licitaciones", []) if isinstance(datos, dict) else datos
    carpeta = ruta_proyecto("informes/mercado")
    carpeta.mkdir(parents=True, exist_ok=True)
    for lic in licitaciones:
        fecha = lic.get("fecha_consulta")
        for item in lic.get("items") or []:
            opciones = []
            for op in item.get("opciones") or []:
                url = str(op.get("url") or "")
                if not url.startswith("https://"):
                    continue
                op["precio_unitario_neto"] = neto_por_unidad(op)
                op.setdefault("fecha_consulta", fecha)
                if op["precio_unitario_neto"] is not None:
                    opciones.append(op)
            item["opciones"] = sorted(opciones, key=lambda o: o["precio_unitario_neto"])
        destino = carpeta / f"{lic['codigo']}.json"
        destino.write_text(json.dumps(lic, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        con_precio = sum(1 for i in lic.get("items") or [] if i["opciones"])
        print(f"{destino.name}: {con_precio}/{len(lic.get('items') or [])} ítems con precio")


if __name__ == "__main__":
    main()
