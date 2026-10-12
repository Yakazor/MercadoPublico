"""Órdenes de compra históricas de mis rubros → precios adjudicados.

Uso:
    python scripts/ordenes_historicas.py --desde 2026-09-01 --hasta 2026-09-30
    python scripts/ordenes_historicas.py --dias 30          # últimos 30 días
    python scripts/ordenes_historicas.py --dias 7 --reprocesar

Los días ya procesados se saltan (se puede cortar y reanudar).
"""
import argparse
import logging
import time
from datetime import date, datetime, timedelta

import _ruta  # noqa: F401
from radar.almacenamiento import BaseDatos, exportar
from radar.cliente_api import ClienteMercadoPublico, ErrorApi
from radar.config import cargar_config, hoy_chile, obtener_ticket, ruta_proyecto
from radar.filtro import FiltroRubros
from radar.ordenes_compra import dias, procesar_dia, reclasificar_items, resumen_precios


MAX_INTENTOS = 3  # tras 3 ejecuciones con OC que fallan, el día se da por cerrado


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
    p.add_argument("--max-minutos", type=float,
                   help="no empieza días nuevos pasado este tiempo (deja margen antes del timeout)")
    p.add_argument("--config")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ayer = hoy_chile() - timedelta(days=1)
    if args.dias:
        desde, hasta = ayer - timedelta(days=args.dias - 1), ayer
    elif args.desde:
        desde, hasta = args.desde, args.hasta or ayer
    else:
        p.error("indica --dias N o --desde AAAA-MM-DD [--hasta AAAA-MM-DD]")
    if hasta > ayer:
        # El día en curso (o futuro) está incompleto: no se marca como procesado.
        logging.warning("--hasta %s se ajusta a ayer (%s): el día de hoy aún no termina.", hasta, ayer)
        hasta = ayer

    config = cargar_config(args.config)
    cliente = ClienteMercadoPublico.desde_config(config, obtener_ticket())
    filtro = FiltroRubros.desde_config(config)
    rutas = config.get("rutas", {})
    db = BaseDatos(ruta_proyecto(rutas.get("base_datos", "data/radar.db")))
    inicio = time.monotonic()
    pendientes: list[str] = []

    try:
        actualizados, eliminados = reclasificar_items(db, filtro)
        if eliminados:
            logging.info("Reclasificación con config actual: %d ítems eliminados, %d actualizados",
                         eliminados, actualizados)

        hasta_monotonic = inicio + args.max_minutos * 60 if args.max_minutos else None
        # Días con fallas de ejecuciones anteriores se reintentan aunque ya hayan
        # quedado fuera de la ventana (--dias), hasta MAX_INTENTOS.
        anteriores = [d for d in db.dias_pendientes() if d < desde]
        if anteriores:
            logging.info("Reintentando días pendientes de ejecuciones anteriores: %s",
                         ", ".join(map(str, anteriores)))
        for fecha in [*anteriores, *dias(desde, hasta)]:
            if not args.reprocesar and db.dia_oc_procesado(fecha):
                logging.info("%s ya procesado, se omite", fecha)
                continue
            if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
                pendientes.append(str(fecha))
                continue
            try:
                r = procesar_dia(cliente, filtro, db, fecha, args.estado, hasta_monotonic)
            except ErrorApi as e:
                intentos = db.registrar_intento_fallido(fecha, ["(listado del día)"])
                if intentos >= MAX_INTENTOS:
                    db.marcar_dia_oc(fecha)
                    logging.error("%s: el listado del día falló %d veces (%s); se da por perdido.",
                                  fecha, intentos, e)
                else:
                    logging.error("%s: no se pudo procesar (%s). Se reintentará en la próxima ejecución "
                                  "(intento %d de %d).", fecha, e, intentos, MAX_INTENTOS)
                    pendientes.append(str(fecha))
                continue
            if r.purgadas:
                logging.info("%s: %d OC guardadas ya no pasan el filtro y se eliminaron", fecha, r.purgadas)
            if r.completo:
                db.marcar_dia_oc(fecha)
                logging.info("%s: %d ítems de %d OC guardados", fecha, r.items, r.ordenes)
            elif r.interrumpido:
                pendientes.append(str(fecha))
            else:
                intentos = db.registrar_intento_fallido(fecha, r.fallidas)
                if intentos >= MAX_INTENTOS:
                    db.marcar_dia_oc(fecha)
                    logging.warning(
                        "%s: %d OC siguen fallando tras %d intentos y se dan por perdidas: %s",
                        fecha, len(r.fallidas), intentos, ", ".join(r.fallidas),
                    )
                else:
                    pendientes.append(str(fecha))
                    logging.warning(
                        "%s: %d de %d OC sin detalle por errores de la API (intento %d de %d); "
                        "el día se reintentará en la próxima ejecución.",
                        fecha, len(r.fallidas), r.candidatas, intentos, MAX_INTENTOS,
                    )

        items = db.items_oc()
        carpeta = ruta_proyecto(rutas.get("exportaciones", "data/exportaciones"))
        archivos = (exportar(items, carpeta, "oc_items", hoy=hoy_chile())
                    + exportar(resumen_precios(items), carpeta, "oc_resumen_precios", hoy=hoy_chile()))
    finally:
        db.cerrar()

    logging.info("Ítems de OC en base: %d", len(items))
    if pendientes:
        logging.warning("Días pendientes (se reintentarán): %s", ", ".join(pendientes))
    for a in archivos:
        logging.info("Exportado: %s", a)


if __name__ == "__main__":
    main()
