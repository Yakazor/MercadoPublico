"""Detalle de una o más Compras Ágiles por código, en Markdown (para el resumen del workflow).

Uso:
    python scripts/detalle_compra_agil.py 1080936-111-COT26 [otro-código ...]

Muestra organismo, fechas, monto, entrega, productos y si calza con tus rubros. Lo
corre el workflow «Detalle Compra Ágil» (Actions → Run workflow → código).
"""
import argparse
import json
import sys

import _ruta  # noqa: F401
from radar.cliente_api import ErrorApi
from radar.compra_agil import URL_FICHA, ClienteCompraAgil, ahora_chile, como_licitacion
from radar.config import cargar_config, obtener_ticket
from radar.filtro import FiltroRubros
from radar.licitaciones import clasificar


def _pesos(v) -> str:
    try:
        return "$" + f"{round(float(v)):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def ficha(codigo: str, det: dict, filtro: FiltroRubros) -> str:
    comprador, fechas = det.get("Comprador") or {}, det.get("Fechas") or {}
    fila = clasificar(det, filtro, ahora_chile().date())
    llamado = {1: "1er llamado (solo empresas de menor tamaño)", 2: "2do llamado"}.get(det.get("Llamado"), "—")
    lineas = [
        f"## [{codigo}]({URL_FICHA.format(codigo)}) {det.get('Nombre') or ''}",
        "",
        f"- **Estado:** {det.get('Estado') or '—'} · **Llamado:** {llamado}",
        f"- **Organismo:** {comprador.get('NombreOrganismo') or '—'} · {comprador.get('NombreUnidad') or ''}",
        f"- **Región:** {comprador.get('RegionUnidad') or '—'}",
        f"- **Publicación:** {fechas.get('FechaPublicacion') or '—'} · **Cierre:** {fechas.get('FechaCierre') or '—'}",
        f"- **Monto disponible:** {_pesos(det.get('MontoEstimado'))} (se cotiza el total con IVA y despacho)",
        f"- **Entrega:** {det.get('DireccionEntrega') or '—'} · plazo {det.get('PlazoEntregaDias') or '—'} días",
        "- **Radar:** " + (f"calza con {fila['rubro_nombre']} ({fila['palabras_detectadas']})" if fila
                             else "no calza con tus rubros"),
    ]
    if det.get("Descripcion"):
        lineas += ["", f"> {' '.join(str(det['Descripcion']).split())}"]
    lineas += ["", "| # | Producto | Descripción del comprador | Cantidad | Unidad |", "|---|---|---|---|---|"]
    for it in (det.get("Items") or {}).get("Listado") or []:
        celdas = [it.get("Correlativo"), it.get("NombreProducto"), it.get("Descripcion"), it.get("Cantidad"),
                  it.get("UnidadMedida")]
        lineas.append("| " + " | ".join(" ".join(str(c if c is not None else "").split()).replace("|", "/")
                                        for c in celdas) + " |")
    return "\n".join(lineas) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("codigos", nargs="+")
    p.add_argument("--json", help="guarda también el detalle crudo en este archivo")
    args = p.parse_args()
    config = cargar_config()
    cliente = ClienteCompraAgil.desde_config(config, obtener_ticket("MP_TICKET_COMPRA_AGIL"))
    filtro = FiltroRubros.desde_config(config)
    crudos, error = {}, False
    for codigo in args.codigos:
        try:
            crudo = cliente.detalle(codigo.strip(), reintentos=3)
        except ErrorApi as e:
            print(f"## {codigo}\n\nNo se pudo obtener el detalle: {e}\n")
            error = True
            continue
        crudos[codigo] = crudo
        print(ficha(codigo, como_licitacion(crudo), filtro))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(crudos, f, ensure_ascii=False, indent=1)
    sys.exit(1 if error else 0)


if __name__ == "__main__":
    main()
