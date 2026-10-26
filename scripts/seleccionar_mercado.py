"""Elige licitaciones para buscarles precios de mercado (presupuesto).

Uso:
    python scripts/seleccionar_mercado.py --items items.json --licitaciones licitaciones.json \
        --salida lote.json [--maximo 4] [--por-rubro 2] [--compras-agiles 2] [--codigos 123-4-LE26,...]

Prioriza licitaciones que se pueden cotizar ítem por ítem: abiertas con tiempo
para ofertar (3+ días; las Compras Ágiles duran 1 o 2 días, a ellas les basta 1), de rubros de productos (no consultoría), que no sean solo
de productos regulados ni incluyan servicios (`compra_venta` no las marca como «no»),
con 1 a 20 ítems concretos (con cantidad, sin "1 Global" ni "según bases"), de un
monto manejable para partir (hasta `--monto-maximo`) y sin precios ya buscados en
informes/mercado/. Ordena por ítems concretos y monto;
como mucho `--por-rubro` licitaciones por rubro. `--compras-agiles N` reserva los primeros N cupos para
Compras Ágiles, primero las de la Región Metropolitana (despacho más barato desde Santiago); no
cuentan en el tope por rubro de las licitaciones. Los días al cierre se cuentan desde hoy (el
`dias_restantes` publicado puede tener horas). Si `compra_agil.soy_emt` es false (config.yaml), salta
las Compras Ágiles de 1er llamado: solo pueden cotizarlas empresas de menor tamaño. Con `--codigos` se buscan esas, aunque no
cumplan los filtros.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import _ruta  # noqa: F401
from radar.config import cargar_config, hoy_chile, ruta_proyecto
from radar.plataforma import COMPRA_AGIL, compra_venta, dias_al_cierre, item_concreto as concreto, soy_emt, solo_emt

DIAS_MINIMOS = 3
DIAS_MINIMOS_COMPRA_AGIL = 1

CAMPOS_ITEM = ("linea", "producto", "descripcion", "cantidad", "unidad", "ref_mediana")


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
    ap.add_argument("--compras-agiles", type=int, default=0,
                    help="cupos reservados para Compras Ágiles (primero las de la Región Metropolitana)")
    args = ap.parse_args()

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    lics = json.loads(Path(args.licitaciones).read_text(encoding="utf-8"))
    ya = {p.stem for p in Path(args.mercado).glob("*.json")}
    pedidos = [c.strip() for c in args.codigos.split(",") if c.strip()]
    hoy = hoy_chile()
    emt = soy_emt(cargar_config())
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
            if not emt and solo_emt(l):              # 1er llamado de Compra Ágil: no puedes cotizar
                continue
            minimo = DIAS_MINIMOS_COMPRA_AGIL if l.get("tipo") == COMPRA_AGIL else DIAS_MINIMOS
            if (dias_al_cierre(l, hoy) or 0) < minimo or not (1 <= len(its) <= 20):
                continue
            if compra_venta(l, its)[0] is False:     # servicios, licencias o registro ISP
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
        agiles = sorted((c for c in candidatas if c[-1].get("tipo") == COMPRA_AGIL),
                        key=lambda c: ("metropolitana" not in (c[-1].get("region") or "").lower(), c[0], c[1]))
        primeras = agiles[:args.compras_agiles]
        orden = primeras + [c for c in candidatas if all(c is not p for p in primeras)]
        elegidas, por_rubro = [], Counter()
        for *_, l in orden:
            if len(elegidas) >= args.maximo:
                break
            reservada = any(l is p[-1] for p in primeras)
            if not reservada:
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
