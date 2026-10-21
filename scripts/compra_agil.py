"""Radar de Compras Ágiles: abiertas a cotización → filtro por rubro → JSON.

Uso:
    python scripts/compra_agil.py                       # escribe data/compras_agiles.json
    python scripts/compra_agil.py --max-detalles 20     # prueba corta

El archivo lo lee `publicar_datos.py`, que suma las Compras Ágiles a
licitaciones.json e items.json (tipo "Compra Ágil") para el dashboard y los
presupuestos. Si la corrida falla, no se escribe nada y el radar de licitaciones
sigue igual.
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import _ruta  # noqa: F401
from radar.cliente_api import ErrorApi
from radar.compra_agil import ClienteCompraAgil, radar_compra_agil
from radar.config import cargar_config, hoy_chile, obtener_ticket, ruta_proyecto
from radar.filtro import FiltroRubros


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", help="archivo JSON (por defecto, rutas.compras_agiles de config.yaml)")
    p.add_argument("--max-detalles", type=int, help="máximo de detalles a pedir (pruebas)")
    p.add_argument("--max-minutos", type=float, help="deja de pedir detalles pasado este tiempo")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    inicio = time.monotonic()

    config = cargar_config()
    ca = config.get("compra_agil", {})
    if not ca.get("activo", True):
        logging.info("Compra Ágil desactivada en config.yaml.")
        return
    cliente = ClienteCompraAgil.desde_config(config, obtener_ticket("MP_TICKET_COMPRA_AGIL"))
    try:
        r = radar_compra_agil(
            cliente,
            FiltroRubros.desde_config(config),
            regiones=ca.get("regiones") or None,
            dias_publicacion=ca.get("dias_publicacion", 15),
            tamano_pagina=ca.get("tamano_pagina", 25),
            max_paginas=ca.get("max_paginas", 200),
            max_detalles=args.max_detalles or ca.get("max_detalles", 400),
            hoy=hoy_chile(),
            hasta_monotonic=inicio + args.max_minutos * 60 if args.max_minutos else None,
        )
    except ErrorApi as e:
        logging.error("API de Compra Ágil: %s", e)
        if e.fatal and not e.temporal:
            logging.error("El ticket no tiene acceso a la API de Compra Ágil (v2). Pide uno en "
                          "https://www.chilecompra.cl/api/ («Pide tu ticket») y guárdalo como secreto "
                          "MP_TICKET_COMPRA_AGIL en GitHub.")
        sys.exit(1)

    salida = ruta_proyecto(args.salida or config.get("rutas", {}).get("compras_agiles", "data/compras_agiles.json"))
    salida.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        "generado": datetime.now(ZoneInfo("America/Santiago")).isoformat(timespec="seconds"),
        "fecha": hoy_chile().isoformat(),
        "regiones": ca.get("regiones") or [],
        "publicadas": r.publicadas,
        "candidatas": r.candidatas,
        "sin_revisar": len(r.fallidas),
        "detenida": r.detenida,
        "llamadas_api": cliente.llamadas,
        "filas": r.filas,
        "detalles": r.detalles,
    }
    salida.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    logging.info("Compras Ágiles: %d publicadas, %d candidatas, %d en tus rubros, %d sin revisar%s. "
                 "Llamadas a la API: %d. Archivo: %s", r.publicadas, r.candidatas, len(r.filas), len(r.fallidas),
                 f" ({r.detenida})" if r.detenida else "", cliente.llamadas, salida)


if __name__ == "__main__":
    main()
