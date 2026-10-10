"""Órdenes de compra históricas de mis rubros → precios adjudicados.

Uso:
    python scripts/ordenes_historicas.py --desde 2026-09-01 --hasta 2026-09-30
    python scripts/ordenes_historicas.py --dias 30          # últimos 30 días
    python scripts/ordenes_historicas.py --dias 7 --reprocesar

Los días ya procesados se saltan (se puede cortar y reanudar).
"""
import argparse
import logging
from datetime import date, datetime, timedelta

import _ruta  # noqa: F401
from radar.almacenamiento import BaseDatos, exportar
from radar.cliente_api import ClienteMercadoPublico, ErrorApi
from radar.config import cargar_config, obtener_ticket, ruta_proyecto
from radar.filtro import FiltroRubros
from radar.ordenes_compra import dias, procesar_dia, resumen_precios


def _fecha(texto: str) -> date:
    for formato in ("%Y-%m-%d", "%d-%m-%Y", "%d%m%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"Fecha inválida: {texto} (usa AAAA-MM-DD o DD-MM-AAAA)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--desde", type=_fecha)
    p.add_argument("--hasta", type=_fecha)
    p.add_argument("--dias", type=int, help="últimos N días (hasta ayer)")
    p.add_argument("--estado", default="todos", help="estado de OC (por defecto: todos)")
    p.add_argument("--reprocesar", action="store_true", help="vuelve a descargar días ya procesados")
    p.add_argument("--config")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ayer = date.today() - timedelta(days=1)
    if args.dias:
        desde, hasta = ayer - timedelta(days=args.dias - 1), ayer
    elif args.desde:
        desde, hasta = args.desde, args.hasta or ayer
    else:
        p.error("indica --dias N o --desde AAAA-MM-DD [--hasta AAAA-MM-DD]")

    config = cargar_config(args.config)
    cliente = ClienteMercadoPublico.desde_config(config, obtener_ticket())
    filtro = FiltroRubros(config["rubros"])
    rutas = config.get("rutas", {})
    db = BaseDatos(ruta_proyecto(rutas.get("base_datos", "data/radar.db")))

    try:
        for fecha in dias(desde, hasta):
            if not args.reprocesar and db.dia_oc_procesado(fecha):
                logging.info("%s ya procesado, se omite", fecha)
                continue
            try:
                n = procesar_dia(cliente, filtro, db, fecha, args.estado)
            except ErrorApi as e:
                logging.error("%s: no se pudo procesar (%s). Se reintentará en la próxima ejecución.", fecha, e)
                continue
            db.marcar_dia_oc(fecha)
            logging.info("%s: %d ítems guardados", fecha, n)

        items = db.items_oc()
        carpeta = ruta_proyecto(rutas.get("exportaciones", "data/exportaciones"))
        archivos = exportar(items, carpeta, "oc_items") + exportar(resumen_precios(items), carpeta, "oc_resumen_precios")
    finally:
        db.cerrar()

    logging.info("Ítems de OC en base: %d", len(items))
    for a in archivos:
        logging.info("Exportado: %s", a)


if __name__ == "__main__":
    main()
