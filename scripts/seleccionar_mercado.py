"""Elige licitaciones para buscarles precios de mercado (presupuesto).

Uso:
    python scripts/seleccionar_mercado.py --items items.json --licitaciones licitaciones.json \
        --salida lote.json [--maximo 4] [--por-rubro 2] [--codigos 123-4-LE26,...]

Prioriza licitaciones que se pueden cotizar ítem por ítem: abiertas con tiempo
para ofertar (3+ días), de rubros de productos (no consultoría), que no sean solo
de productos regulados, con 1 a 20 ítems concretos (con cantidad, sin "1 Global"
ni "según bases"), de un monto manejable para partir (hasta `--monto-maximo`) y
sin precios ya buscados en informes/mercado/. Ordena por ítems concretos y monto;
como mucho `--por-rubro` por rubro. Con `--codigos` se buscan esas, aunque no
cumplan los filtros.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import _ruta  # noqa: F401
from radar.config import ruta_proyecto

CAMPOS_ITEM = ("linea", "producto", "descripcion", "cantidad", "unidad", "ref_mediana")
_GLOBAL = {"global", "unidad no definida", "servicio"}
_SEGUN = re.compile(r"seg[uú]n (bases|detalle|cantidades|anexo|especificaciones|lo indicado)|de acuerdo a (las )?bases", re.I)
# Descripciones que nombran una categoría y no un producto ("Mobiliario para la oficina X").
_GENERICA = re.compile(r"^(mobiliario|insumos|materiales|equipamiento|articulos|art[ií]culos|equipos|productos)\b", re.I)
# Licencias y soporte de software: exigen ser partner del fabricante, no se compran y revenden.
_SOFTWARE = re.compile(r"licenci|software|soporte|suscripci", re.I)


def concreto(item: dict) -> bool:
    """Ítem que se puede cotizar: cantidad, unidad física y una descripción propia."""
    descripcion = (item.get("descripcion") or "").strip()
    unidad = (item.get("unidad") or "").strip().lower()
    return (bool(item.get("cantidad")) and unidad not in _GLOBAL and len(descripcion) >= 8
            and not _SEGUN.search(descripcion) and not _GENERICA.search(descripcion)
            and not _SOFTWARE.search(f"{item.get('producto') or ''} {descripcion}"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", required=True)
    ap.add_argument("--licitaciones", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--mercado", default=str(ruta_proyecto("informes/mercado")))
    ap.add_argument("--maximo", type=int, default=4)
    ap.add_argument("--por-rubro", type=int, default=2)
    ap.add_argument("--monto-maximo", type=float, default=60_000_000, help="monto estimado máximo en CLP")
    ap.add_argument("--codigos", default="", help="códigos separados por coma (se buscan sí o sí)")
    args = ap.parse_args()

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    lics = json.loads(Path(args.licitaciones).read_text(encoding="utf-8"))
    ya = {p.stem for p in Path(args.mercado).glob("*.json")}
    pedidos = [c.strip() for c in args.codigos.split(",") if c.strip()]
    por_codigo = defaultdict(list)
    for it in items:
        por_codigo[it["codigo"]].append(it)

    def ficha(l):
        return {
            **{k: l.get(k) for k in ("codigo", "nombre", "rubro", "rubro_nombre", "organismo", "region",
                                     "fecha_cierre", "monto_estimado", "moneda")},
            "items": [{k: i.get(k) for k in CAMPOS_ITEM} for i in por_codigo.get(l["codigo"], [])],
        }

    if pedidos:
        elegidas = [ficha(l) for l in lics if l["codigo"] in pedidos]
    else:
        candidatas = []
        for l in lics:
            its = por_codigo.get(l["codigo"], [])
            if l["codigo"] in ya or l.get("rubro") == "consultoria_gestion_bi" or l.get("solo_regulados"):
                continue
            if (l.get("dias_restantes") or 0) < 3 or not (1 <= len(its) <= 20):
                continue
            concretos = sum(concreto(i) for i in its)
            if concretos < max(1, 0.8 * len(its)):
                continue
            monto = l.get("monto_estimado") if l.get("moneda") in (None, "CLP") else None
            if monto and monto > args.monto_maximo:
                continue
            # Mejor con varios ítems concretos (un presupuesto de verdad) y monto conocido.
            candidatas.append((-min(concretos, 15), -(monto or 0), l))
        candidatas.sort(key=lambda c: (c[0], c[1]))
        elegidas, por_rubro = [], Counter()
        for *_, l in candidatas:
            if len(elegidas) >= args.maximo:
                break
            if por_rubro[l["rubro"]] >= args.por_rubro:
                continue
            por_rubro[l["rubro"]] += 1
            elegidas.append(ficha(l))
    Path(args.salida).write_text(json.dumps(elegidas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(elegidas)} licitaciones, {sum(len(e['items']) for e in elegidas)} ítems")
    for e in elegidas:
        print(f"  {e['codigo']}  {e['rubro']}  {len(e['items'])} ítems  {e['nombre'][:70]}")


if __name__ == "__main__":
    main()
