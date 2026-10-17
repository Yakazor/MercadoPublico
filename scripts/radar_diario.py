"""Radar diario: licitaciones activas → filtro por rubro → SQLite → CSV/Excel.

Uso:
    python scripts/radar_diario.py              # ejecución normal
    python scripts/radar_diario.py --limite 10  # prueba con 10 detalles
"""
import argparse
import logging
import time

import _ruta  # noqa: F401
from radar.almacenamiento import BaseDatos, exportar
from radar.cliente_api import ClienteMercadoPublico
from radar.config import cargar_config, hoy_chile, obtener_ticket, ruta_proyecto
from radar.filtro import FiltroRubros
from radar.licitaciones import ResultadoRadar, radar_licitaciones


def listado_completo(activas: set[str], vigentes, minimo: float = 0.8) -> bool:
    """False si el listado de activas viene vacío o recortado (falla de la API): en
    ese caso no se borra nada de la base ni de la caché de detalles."""
    if not activas:
        logging.warning("El listado de activas vino vacío: no se depura la base.")
        return False
    if vigentes is None or vigentes.empty or "codigo" not in vigentes:
        return True
    proporcion = vigentes["codigo"].isin(activas).mean()
    if proporcion < minimo:
        logging.warning("Solo %.0f%% de las vigentes guardadas aparece en el listado de activas: "
                        "no se depura la base (¿listado recortado?).", proporcion * 100)
        return False
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limite", type=int, help="máximo de detalles a consultar (pruebas)")
    p.add_argument("--config", help="ruta alternativa a config.yaml")
    p.add_argument("--solo-exportar", action="store_true",
                   help="no llama a la API: re-exporta lo que ya está en la base")
    p.add_argument("--max-minutos", type=float,
                   help="deja de pedir detalles pasado este tiempo (las que falten se conservan)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    inicio = time.monotonic()
    listado_ok = False

    config = cargar_config(args.config)
    rutas = config.get("rutas", {})
    db = BaseDatos(ruta_proyecto(rutas.get("base_datos", "data/radar.db")))
    try:
        if args.solo_exportar:
            resultado = ResultadoRadar()
        else:
            cliente = ClienteMercadoPublico.desde_config(config, obtener_ticket())
            resultado = radar_licitaciones(
                cliente,
                FiltroRubros.desde_config(config),
                preliminar_por_nombre=config.get("filtro_preliminar_por_nombre", True),
                limite=args.limite,
                hoy=hoy_chile(),
                db=db,
                refrescar_dias=config.get("refrescar_detalle_licitacion_dias", 7),
                hasta_monotonic=inicio + args.max_minutos * 60 if args.max_minutos else None,
            )
            listado_ok = listado_completo(resultado.activas, db.licitaciones_vigentes(hoy=hoy_chile()))
            if not args.limite and listado_ok:
                db.podar_detalles_licitacion(resultado.activas)
        filas = resultado.filas
        db.guardar_licitaciones(filas)
        if not args.solo_exportar and not args.limite and listado_ok:
            # Las que fallaron por la API no se revisaron: se conservan tal cual.
            conservar = {f["codigo"] for f in filas} | resultado.fallidas
            eliminadas = db.depurar_vigentes(conservar, hoy=hoy_chile())
            if eliminadas:
                logging.info("Eliminadas de la base (ya no pasan el filtro): %d", eliminadas)
        if resultado.fallidas:
            logging.warning(
                "%d de %d candidatas sin revisar (errores de la API o sin tiempo); se conservan sus datos anteriores.",
                len(resultado.fallidas), resultado.candidatas,
            )
        vigentes = db.licitaciones_vigentes(hoy=hoy_chile())
        archivos = exportar(vigentes, ruta_proyecto(rutas.get("exportaciones", "data/exportaciones")),
                            "licitaciones", hoy=hoy_chile())
    finally:
        db.cerrar()

    logging.info("Nuevas/actualizadas hoy: %d | Vigentes en base: %d", len(filas), len(vigentes))
    if not vigentes.empty:
        logging.info("Por rubro:\n%s", vigentes["rubro_nombre"].value_counts().to_string())
    for a in archivos:
        logging.info("Exportado: %s", a)


if __name__ == "__main__":
    main()
