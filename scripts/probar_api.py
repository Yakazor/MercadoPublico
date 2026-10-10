"""Hace UNA llamada real a la API y muestra la estructura del JSON.

Uso:
    python scripts/probar_api.py                       # licitaciones activas (resumen)
    python scripts/probar_api.py --codigo 1234-56-LE26 # detalle de una licitación
    python scripts/probar_api.py --oc 1234-56-SE26     # detalle de una orden de compra
"""
import argparse
import json

import _ruta  # noqa: F401
from radar.cliente_api import ClienteMercadoPublico
from radar.config import cargar_config, obtener_ticket, ruta_proyecto


def estructura(valor, nivel=0, max_lista=1):
    sangria = "  " * nivel
    if isinstance(valor, dict):
        for clave, v in valor.items():
            if isinstance(v, (dict, list)):
                print(f"{sangria}{clave}: {type(v).__name__}" + (f"[{len(v)}]" if isinstance(v, list) else ""))
                estructura(v, nivel + 1, max_lista)
            else:
                print(f"{sangria}{clave}: {json.dumps(v, ensure_ascii=False)[:70]}")
    elif isinstance(valor, list):
        for elem in valor[:max_lista]:
            print(f"{sangria}- [0]")
            estructura(elem, nivel + 1, max_lista)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--codigo", help="código de licitación")
    p.add_argument("--oc", help="código de orden de compra")
    args = p.parse_args()

    cliente = ClienteMercadoPublico.desde_config(cargar_config(), obtener_ticket())
    if args.oc:
        datos = cliente.ordenes_de_compra(codigo=args.oc)
    elif args.codigo:
        datos = cliente.licitaciones(codigo=args.codigo)
    else:
        datos = cliente.licitaciones(estado="activas")

    salida = ruta_proyecto("data/muestra_api.json")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    estructura(datos)
    print(f"\nRespuesta completa guardada en {salida}")


if __name__ == "__main__":
    main()
