"""Censo de grupos de licitaciones (segmentos del clasificador ONU).

Uso (en GitHub Actions, con MP_TICKET):
    python scripts/censo_rubros.py --muestra 1200 --salida /tmp/censo --max-minutos 150

Pide el detalle de una muestra estable de las licitaciones activas (una llamada
por licitación, con la pausa de config.yaml) y escribe censo.json con cuántas
licitaciones y qué monto hay en cada segmento y familia ONU, y cuántas detecta el
radar con los rubros actuales. Con `--desde-json` rehace el resumen sin la API.
"""
import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import _ruta  # noqa: F401
from radar.censo import agregar_censo, muestra_estable
from radar.cliente_api import ClienteMercadoPublico, ErrorApi
from radar.config import cargar_config, obtener_ticket
from radar.filtro import FiltroRubros
from radar.licitaciones import detalle, listar_activas

log = logging.getLogger("censo")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--muestra", type=int, default=1200)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--max-minutos", type=float, default=150)
    ap.add_argument("--desde-json", help="detalles.json de una corrida anterior (no llama a la API)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = cargar_config()
    filtro = FiltroRubros.desde_config(config)
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    if args.desde_json:
        guardado = json.loads(Path(args.desde_json).read_text(encoding="utf-8"))
        activas_total, detalles = guardado["activas_total"], guardado["detalles"]
    else:
        cliente = ClienteMercadoPublico.desde_config(config, obtener_ticket())
        activas = listar_activas(cliente)
        activas_total = len(activas)
        codigos = muestra_estable([a.get("CodigoExterno") for a in activas if a.get("CodigoExterno")], args.muestra)
        log.info("Activas: %d; muestra: %d", activas_total, len(codigos))
        hasta = time.monotonic() + args.max_minutos * 60
        detalles = []
        for i, codigo in enumerate(codigos, 1):
            if time.monotonic() > hasta:
                log.warning("Tiempo agotado: %d de %d detalles", len(detalles), len(codigos))
                break
            try:
                det = detalle(cliente, codigo)
            except ErrorApi as e:
                if e.fatal:
                    raise
                log.error("Sin detalle para %s: %s", codigo, e)
                continue
            if det:
                detalles.append({k: det.get(k) for k in ("CodigoExterno", "Nombre", "Tipo", "MontoEstimado", "Moneda",
                                                         "Descripcion", "Items", "Fechas", "Comprador")})
            if i % 100 == 0:
                log.info("Detalle %d/%d", i, len(codigos))
        (salida / "detalles.json").write_text(
            json.dumps({"activas_total": activas_total, "detalles": detalles}, ensure_ascii=False), encoding="utf-8")

    censo = agregar_censo(detalles, filtro, activas_total)
    censo["generado"] = datetime.now(ZoneInfo("America/Santiago")).isoformat(timespec="seconds")
    censo["rubros_config"] = {clave: datos.get("nombre", clave) for clave, datos in (config.get("rubros") or {}).items()}
    (salida / "censo.json").write_text(json.dumps(censo, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Censo: %d segmentos en %d licitaciones (%d detectadas por el radar)",
             len(censo["segmentos"]), censo["procesadas"], censo["detectadas_por_el_radar"])


if __name__ == "__main__":
    main()
