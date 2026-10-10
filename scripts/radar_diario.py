"""Radar diario: licitaciones activas → filtro por rubro → SQLite → CSV/Excel.

Uso:
    python scripts/radar_diario.py              # ejecución normal
    python scripts/radar_diario.py --limite 10  # prueba con 10 detalles
"""
import argparse
import logging

import _ruta  # noqa: F401
from radar.almacenamiento import BaseDatos, exportar
from radar.cliente_api import ClienteMercadoPublico
from radar.config import cargar_config, obtener_ticket, ruta_proyecto
from radar.filtro import FiltroRubros
from radar.licitaciones import radar_licitaciones


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limite", type=int, help="máximo de detalles a consultar (pruebas)")
    p.add_argument("--config", help="ruta alternativa a config.yaml")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = cargar_config(args.config)
    cliente = ClienteMercadoPublico.desde_config(config, obtener_ticket())
    filtro = FiltroRubros(config["rubros"])

    filas = radar_licitaciones(
        cliente,
        filtro,
        preliminar_por_nombre=config.get("filtro_preliminar_por_nombre", True),
        limite=args.limite,
    )

    rutas = config.get("rutas", {})
    db = BaseDatos(ruta_proyecto(rutas.get("base_datos", "data/radar.db")))
    try:
        db.guardar_licitaciones(filas)
        vigentes = db.licitaciones_vigentes()
        archivos = exportar(vigentes, ruta_proyecto(rutas.get("exportaciones", "data/exportaciones")), "licitaciones")
    finally:
        db.cerrar()

    logging.info("Nuevas/actualizadas hoy: %d | Vigentes en base: %d", len(filas), len(vigentes))
    if not vigentes.empty:
        logging.info("Por rubro:\n%s", vigentes["rubro_nombre"].value_counts().to_string())
    for a in archivos:
        logging.info("Exportado: %s", a)


if __name__ == "__main__":
    main()
