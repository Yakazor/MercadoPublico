"""Censo de grupos de licitaciones: con qué productos compra el Estado.

Toma una muestra estable de las licitaciones activas, lee la categoría del
clasificador ONU de cada ítem (segmento / familia / clase) y cuenta, por segmento
y familia, cuántas licitaciones hay, cuánto suman y cuántas detecta el radar con
los rubros de config.yaml. Sirve para decidir si conviene agregar rubros.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from .filtro import FiltroRubros
from .licitaciones import clasificar
from .modelos import items_licitacion


def muestra_estable(codigos: list[str], n: int) -> list[str]:
    """Los `n` códigos con menor hash: la misma muestra si se repite el día."""
    return sorted(codigos, key=lambda c: hashlib.sha1(str(c).encode()).hexdigest())[:n]


def _niveles(item: dict) -> tuple[str, str, str | None]:
    """(código de segmento, nombre de segmento, nombre de familia)."""
    partes = [p.strip() for p in str(item.get("Categoria") or "").split("/") if p.strip()]
    codigo = "".join(ch for ch in str(item.get("CodigoCategoria") or "") if ch.isdigit())
    segmento = partes[0] if partes else "Sin categoría"
    return (codigo[:2] or "??", segmento, partes[1] if len(partes) > 1 else None)


def _monto_clp(detalle: dict) -> float:
    try:
        monto = float(detalle.get("MontoEstimado") or 0)
    except (TypeError, ValueError):
        return 0.0
    return monto if (detalle.get("Moneda") or "CLP") == "CLP" else 0.0


def agregar_censo(detalles: list[dict], filtro: FiltroRubros, activas_total: int, ejemplos: int = 4) -> dict:
    """Resumen por segmento ONU. Una licitación cuenta una vez en cada segmento que
    compra; su monto estimado se reparte entre segmentos según sus ítems."""
    seg = defaultdict(lambda: {"licitaciones": set(), "items": 0, "monto_clp": 0.0, "detectadas": set(),
                               "rubros": Counter(), "familias": Counter(), "ejemplos": []})
    nombres_seg: dict[str, Counter] = defaultdict(Counter)
    por_tipo = Counter()
    detectadas_total = 0
    for det in detalles:
        codigo = det.get("CodigoExterno")
        items = items_licitacion(det)
        fila = clasificar(det, filtro)
        if fila:
            detectadas_total += 1
        por_tipo[det.get("Tipo") or "?"] += 1
        if not items:
            items = [{}]
        conteo = Counter(_niveles(i)[0] for i in items)
        familias_lic = defaultdict(set)
        for item in items:
            cod, nombre, familia = _niveles(item)
            nombres_seg[cod][nombre] += 1
            seg[cod]["items"] += 1
            if familia:
                familias_lic[cod].add(familia)
        for cod, n in conteo.items():
            s = seg[cod]
            s["licitaciones"].add(codigo)
            s["monto_clp"] += _monto_clp(det) * n / len(items)
            for familia in familias_lic[cod]:
                s["familias"][familia] += 1
            if fila:
                s["detectadas"].add(codigo)
                s["rubros"][fila["rubro"]] += 1
            if len(s["ejemplos"]) < ejemplos and det.get("Nombre"):
                s["ejemplos"].append(str(det["Nombre"]).strip()[:120])
    procesadas = len(detalles)
    factor = activas_total / procesadas if procesadas else 0
    segmentos = []
    for cod, s in seg.items():
        n = len(s["licitaciones"])
        segmentos.append({
            "codigo": cod,
            "segmento": nombres_seg[cod].most_common(1)[0][0],
            "licitaciones": n,
            "porcentaje": round(100 * n / procesadas, 1) if procesadas else 0,
            "estimado_activas": round(n * factor),
            "items": s["items"],
            "monto_clp_muestra": round(s["monto_clp"]),
            "monto_clp_estimado": round(s["monto_clp"] * factor),
            "detectadas": len(s["detectadas"]),
            "cobertura": round(100 * len(s["detectadas"]) / n, 1) if n else 0,
            "rubros": dict(s["rubros"].most_common()),
            "familias": [{"familia": f, "licitaciones": c} for f, c in s["familias"].most_common(12)],
            "ejemplos": s["ejemplos"],
        })
    segmentos.sort(key=lambda s: -s["licitaciones"])
    return {
        "activas_total": activas_total,
        "procesadas": procesadas,
        "detectadas_por_el_radar": detectadas_total,
        "por_tipo": dict(por_tipo.most_common()),
        "segmentos": segmentos,
    }
