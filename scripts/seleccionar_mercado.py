"""Elige licitaciones para buscarles precios de mercado (presupuesto).

Uso:
    python scripts/seleccionar_mercado.py --items items.json --licitaciones licitaciones.json \
        --salida lote.json [--maximo 4] [--por-rubro 2] [--compras-agiles 2] [--codigos 123-4-LE26,...]

Prioriza licitaciones que se pueden cotizar ítem por ítem: abiertas con tiempo
para ofertar (3+ días; las Compras Ágiles duran 1 o 2 días, a ellas les basta 1), de rubros de productos (no consultoría), que no sean solo
de productos regulados ni incluyan servicios (`compra_venta` no las marca como «no»),
con 1 a 20 ítems concretos (con cantidad, sin "1 Global" ni "según bases"), de un
monto manejable para partir (hasta `--monto-maximo`). Las que ya tienen precios en informes/mercado/
pero tienen líneas que nunca se buscaron van primero y solo con esas líneas (`completar: true`);
`guardar_mercado.py` combina lo nuevo con lo anterior. Una línea ya buscada sin precio (queda en el JSON
con `opciones: []`) no se repite: necesita cotización de un proveedor (`--reintentar` la vuelve a buscar). Ordena por ítems concretos y monto;
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
from radar.evaluacion import NO_GO, evaluar
from radar.plataforma import (COMPRA_AGIL, compra_venta, dias_al_cierre, item_concreto as concreto, soy_emt, solo_emt,
                              supuestos_config)
from radar.presupuesto import armar_presupuesto

DIAS_MINIMOS = 3
DIAS_MINIMOS_COMPRA_AGIL = 1

CAMPOS_ITEM = ("linea", "producto", "descripcion", "cantidad", "unidad", "ref_mediana")


def sin_remedio(lic: dict, items: list[dict], archivo: Path, supuestos: dict) -> bool:
    """NO GO por precio (sobre el monto estimado o sobre lo que pagó el Estado) con lo que ya hay:
    completar las líneas que faltan solo sube la oferta, así que no vale la pena gastar en ellas."""
    from presupuesto import opciones_mercado
    try:
        mercado = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    p = armar_presupuesto(items, opciones_mercado(mercado), iva_es_costo=not supuestos["recupera_iva_compras"])
    if len(p["items"]) == p["items_sin_precio"]:
        return False
    ev = evaluar(lic | {"dias_restantes": None}, p, supuestos)
    return ev.decision == NO_GO and any("monto" in r or "órdenes de compra" in r or "tope" in r for r in ev.razones)


def lineas_buscadas(carpeta: Path) -> dict[str, set]:
    """{código: líneas que ya se buscaron, con o sin precio} de informes/mercado/. Una línea buscada
    sin resultado queda en el JSON con `opciones: []` y su nota («pedir cotización a distribuidor»)."""
    salida = {}
    for archivo in carpeta.glob("*.json"):
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = datos.get("items") if isinstance(datos, dict) else None
        salida[archivo.stem] = {i.get("linea") for i in items or []}
    return salida


def lineas_con_precio(carpeta: Path) -> dict[str, set]:
    """{código: líneas con al menos una opción de precio} de informes/mercado/."""
    salida = {}
    for archivo in carpeta.glob("*.json"):
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = datos.get("items") if isinstance(datos, dict) else None
        salida[archivo.stem] = {i.get("linea") for i in items or []
                                if any(not o.get("descartado") and o.get("precio_unitario_neto")
                                       for o in i.get("opciones") or [])}
    return salida


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
    ap.add_argument("--reintentar", action="store_true",
                    help="vuelve a buscar también las líneas ya buscadas sin precio (por defecto no se repiten)")
    ap.add_argument("--compras-agiles", type=int, default=0,
                    help="cupos reservados para Compras Ágiles (primero las de la Región Metropolitana)")
    args = ap.parse_args()

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    lics = json.loads(Path(args.licitaciones).read_text(encoding="utf-8"))
    con_precio = lineas_con_precio(Path(args.mercado))
    # Lo ya buscado no se repite: del 03 al 09-11 la rutina volvió cada día sobre las mismas líneas sin
    # precio en tiendas («6 a completar, sin precios nuevos»). Esas líneas necesitan cotización de proveedor.
    buscadas = con_precio if args.reintentar else lineas_buscadas(Path(args.mercado))
    pedidos = [c.strip() for c in args.codigos.split(",") if c.strip()]
    hoy = hoy_chile()
    config = cargar_config()
    emt = soy_emt(config)
    supuestos = supuestos_config(config)
    por_codigo = defaultdict(list)
    for it in items:
        por_codigo[it["codigo"]].append(it)

    def ficha(l, its=None):
        completar = its is not None
        its = por_codigo.get(l["codigo"], []) if its is None else its
        return {
            **{k: l.get(k) for k in ("codigo", "nombre", "rubro", "rubro_nombre", "organismo", "region",
                                     "fecha_cierre", "monto_estimado", "moneda")},
            "items": [{k: i.get(k) for k in CAMPOS_ITEM} for i in its],
            **({"completar": True} if completar else {}),
        }

    if pedidos:
        elegidas = [ficha(l) for l in lics if l["codigo"] in pedidos]
    else:
        candidatas = []
        faltantes = {}
        for l in lics:
            its = por_codigo.get(l["codigo"], [])
            if l["codigo"] in con_precio:
                # Ya buscada: solo vuelve si le faltan líneas (y sí tiene alguna con precio).
                its_faltan = [i for i in its if i.get("linea") not in buscadas.get(l["codigo"], ())]
                # Sin líneas faltantes, o una búsqueda anterior que no encontró nada: no se repite.
                if not its_faltan or not con_precio[l["codigo"]]:
                    continue
                if sin_remedio(l, its, Path(args.mercado) / f"{l['codigo']}.json", supuestos):
                    continue
                faltantes[l["codigo"]] = its = its_faltan
            if l.get("rubro") == "consultoria_gestion_bi" or l.get("solo_regulados"):
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
            # Primero las que quedaron a medias (con las líneas que faltan pueden pasar a GO); después,
            # mejor con varios ítems concretos (un presupuesto de verdad) y monto conocido.
            candidatas.append((l["codigo"] not in faltantes, -min(concretos, 15), -(monto or 0), l))
        candidatas.sort(key=lambda c: (c[0], c[1], c[2]))
        agiles = sorted((c for c in candidatas if c[-1].get("tipo") == COMPRA_AGIL),
                        key=lambda c: ("metropolitana" not in (c[-1].get("region") or "").lower(), c[0], c[1], c[2]))
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
            elegidas.append(ficha(l, faltantes.get(l["codigo"])))
    Path(args.salida).write_text(json.dumps(elegidas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(elegidas)} licitaciones, {sum(len(e['items']) for e in elegidas)} ítems")
    for e in elegidas:
        print(f"  {e['codigo']}  {e['rubro']}  {len(e['items'])} ítems{' (completar)' if e.get('completar') else ''}"
              f"  {e['nombre'][:70]}")


if __name__ == "__main__":
    main()
