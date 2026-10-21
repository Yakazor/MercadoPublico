"""Radar de Compras Ágiles: abiertas a cotización → filtro por rubro → JSON.

Uso:
    python scripts/compra_agil.py                       # corrida incremental
    python scripts/compra_agil.py --max-detalles 20     # prueba corta

Cada corrida lista solo lo publicado desde la anterior (la API entrega ~10 compras
cada ~5 s, así que listar todo Chile de una vez toma horas) y guarda lo encontrado en
una memoria (`rutas.compra_agil_estado`, en la caché de GitHub Actions). Escribe:

    rutas.compras_agiles   Compras Ágiles abiertas de tus rubros (filas + detalles), que
                           `publicar_datos.py` suma a licitaciones.json e items.json.

Lo corre el workflow «Compras Ágiles» cada 3 horas; el radar diario lee el resultado.
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
from radar.compra_agil import ClienteCompraAgil, actualizar_compras_agiles, ahora_chile, estado_vacio
from radar.config import cargar_config, obtener_ticket, ruta_proyecto
from radar.filtro import FiltroRubros
from radar.modelos import _fecha, dias_restantes


def leer_estado(ruta) -> dict:
    try:
        estado = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return estado_vacio()
    return estado if estado.get("version") == 1 else estado_vacio()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max-detalles", type=int, help="máximo de detalles a pedir (pruebas)")
    p.add_argument("--max-minutos", type=float, help="deja de consultar la API pasado este tiempo")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    inicio = time.monotonic()

    config = cargar_config()
    ca = config.get("compra_agil", {})
    if not ca.get("activo", True):
        logging.info("Compra Ágil desactivada en config.yaml.")
        return
    rutas = config.get("rutas", {})
    ruta_estado = ruta_proyecto(rutas.get("compra_agil_estado", "data/compra_agil_estado.json"))
    ruta_salida = ruta_proyecto(rutas.get("compras_agiles", "data/compras_agiles.json"))
    estado = leer_estado(ruta_estado)
    cliente = ClienteCompraAgil.desde_config(config, obtener_ticket("MP_TICKET_COMPRA_AGIL"))
    codigo_salida = 0
    try:
        r = actualizar_compras_agiles(
            cliente,
            FiltroRubros.desde_config(config),
            estado,
            regiones=ca.get("regiones") or None,
            dias_iniciales=ca.get("dias_iniciales", 3),
            tamano_pagina=ca.get("tamano_pagina", 10),
            max_paginas=ca.get("max_paginas", 400),
            max_detalles=args.max_detalles or ca.get("max_detalles", 700),
            hasta_monotonic=inicio + args.max_minutos * 60 if args.max_minutos else None,
        )
    except ErrorApi as e:
        # Lo obtenido hasta el error ya está en `estado`: se guarda igual.
        logging.error("API de Compra Ágil: %s", e)
        if e.fatal and not e.temporal:
            logging.error("El ticket no tiene acceso a la API de Compra Ágil (v2). Pide uno en "
                          "https://www.chilecompra.cl/api/ («Pide tu ticket») y guárdalo como secreto "
                          "MP_TICKET_COMPRA_AGIL en GitHub.")
        r, codigo_salida = None, 1

    ruta_estado.parent.mkdir(parents=True, exist_ok=True)
    ruta_estado.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    hoy = ahora_chile().date()
    filas = []
    for codigo, abierta in sorted(estado["abiertas"].items()):
        fila = dict(abierta["fila"])
        fila["dias_restantes"] = dias_restantes(_fecha(str(fila.get("fecha_cierre") or "").replace(" ", "T")), hoy)
        filas.append(fila)
    datos = {
        "generado": datetime.now(ZoneInfo("America/Santiago")).isoformat(timespec="seconds"),
        "fecha": hoy.isoformat(),
        "listado_hasta": estado.get("listado_hasta"),
        "regiones": ca.get("regiones") or [],
        "pendientes": len(estado["pendientes"]),
        "detenida": r.detenida if r else "error de la API",
        "llamadas_api": cliente.llamadas,
        "filas": filas,
        "detalles": {codigo: a["detalle"] for codigo, a in estado["abiertas"].items()},
    }
    ruta_salida.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    logging.info("Abiertas en tus rubros: %d · pendientes: %d · listado completo hasta %s · llamadas: %d",
                 len(filas), len(estado["pendientes"]), estado.get("listado_hasta"), cliente.llamadas)
    sys.exit(codigo_salida)


if __name__ == "__main__":
    main()
