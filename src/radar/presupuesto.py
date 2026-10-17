"""Presupuesto de una licitación: sus ítems, el precio que el Estado ya pagó por
productos parecidos (OC) y el mejor precio encontrado en el mercado chileno.

- `ReferenciasOC`: precio adjudicado en órdenes de compra para el producto de cada
  ítem (mismo producto ONU o, si no, el más parecido por palabras).
- `items_licitacion_presupuesto`: filas de ítems (cantidad, unidad y referencia OC).
- `armar_presupuesto`: costo de compra, oferta sugerida y margen por ítem, con los
  precios de mercado que se buscaron aparte (`informes/mercado/<codigo>.json`).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from .filtro import normalizar
from .modelos import items_licitacion

IVA = 0.19
_VACIAS = {"de", "del", "la", "el", "los", "las", "para", "con", "y", "o", "e", "en", "por", "a", "al",
           "x", "un", "una", "uno", "sin", "tipo", "segun", "otros", "otras", "u"}
SIMILITUD_MINIMA = 0.5


def _palabras(texto: str) -> set[str]:
    return {p for p in normalizar(texto).split() if p not in _VACIAS and len(p) > 1}


def _numero(valor) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(n) else n


@dataclass
class Referencia:
    producto: str
    mediana: float
    p25: float
    n_ordenes: int
    similitud: float
    rubro: str | None


class ReferenciasOC:
    """Precio unitario neto adjudicado (CLP) por producto, para comparar la oferta."""

    def __init__(self, precios: pd.DataFrame):
        df = precios[precios["moneda"].fillna("CLP") == "CLP"] if not precios.empty else precios
        self._exactas: dict[str, dict] = {}
        self._filas: list[dict] = []
        self._indice: dict[str, list[int]] = defaultdict(list)
        for fila in df.sort_values("n_ordenes", ascending=False).to_dict("records"):
            producto = fila.get("producto_normalizado") or ""
            if not producto or _numero(fila.get("precio_mediana")) is None:
                continue
            self._exactas.setdefault(producto, fila)
            i = len(self._filas)
            self._filas.append(fila | {"_palabras": _palabras(producto)})
            for p in self._filas[i]["_palabras"]:
                self._indice[p].append(i)

    def buscar(self, producto: str | None, descripcion: str | None = None, rubro: str | None = None) -> Referencia | None:
        """Mismo producto ONU; si no, el más parecido (Jaccard ≥ 0,5 y 2+ palabras en
        común) entre el producto y la descripción del ítem, prefiriendo su rubro."""
        exacta = self._exactas.get(normalizar(producto))
        if exacta is not None:
            return self._referencia(exacta, 1.0)
        buscadas = _palabras(f"{producto or ''} {descripcion or ''}")
        if not buscadas:
            return None
        candidatas = {i for p in buscadas for i in self._indice.get(p, ())}
        mejor, mejor_nota = None, (0.0, False, 0)
        for i in candidatas:
            fila = self._filas[i]
            comunes = buscadas & fila["_palabras"]
            if len(comunes) < 2:
                continue
            # Cuánto del producto de la OC aparece en el ítem (la descripción es más larga).
            similitud = len(comunes) / len(fila["_palabras"])
            nota = (similitud, fila.get("rubro") == rubro, fila.get("n_ordenes") or 0)
            if similitud >= SIMILITUD_MINIMA and nota > mejor_nota:
                mejor, mejor_nota = fila, nota
        return self._referencia(mejor, mejor_nota[0]) if mejor is not None else None

    @staticmethod
    def _referencia(fila: dict, similitud: float) -> Referencia:
        return Referencia(
            producto=fila.get("producto_normalizado"),
            mediana=float(fila["precio_mediana"]),
            p25=float(_numero(fila.get("precio_p25")) or fila["precio_mediana"]),
            n_ordenes=int(fila.get("n_ordenes") or 0),
            similitud=round(similitud, 2),
            rubro=fila.get("rubro"),
        )


def items_licitacion_presupuesto(codigo: str, rubro: str | None, detalle: dict,
                                 referencias: ReferenciasOC | None = None) -> list[dict]:
    """Una fila por ítem de la licitación, con su referencia de precio en OC."""
    filas = []
    for n, item in enumerate(items_licitacion(detalle), 1):
        producto = item.get("NombreProducto")
        descripcion = (item.get("Descripcion") or "").strip()
        ref = referencias.buscar(producto, descripcion, rubro) if referencias is not None else None
        filas.append({
            "codigo": codigo,
            "linea": int(_numero(item.get("Correlativo")) or n),
            "producto": producto,
            "descripcion": descripcion[:400] or None,
            "categoria": item.get("Categoria"),
            "cantidad": _numero(item.get("Cantidad")),
            "unidad": item.get("UnidadMedida"),
            "ref_producto": ref.producto if ref else None,
            "ref_mediana": ref.mediana if ref else None,
            "ref_p25": ref.p25 if ref else None,
            "ref_n_ordenes": ref.n_ordenes if ref else None,
            "ref_similitud": ref.similitud if ref else None,
        })
    return filas


def armar_presupuesto(items: list[dict], mercado: list[dict], margen: float = 0.20,
                      otros_costos: float = 0.05) -> dict:
    """Presupuesto por ítem con el mejor precio de mercado encontrado.

    - costo unitario = precio neto (sin IVA) por unidad pedida en la licitación;
    - costo con otros gastos = costo × (1 + otros_costos) (despacho, boletas, etc.);
    - oferta sugerida = costo con gastos × (1 + margen), pero si la referencia OC
      (mediana adjudicada) es menor, se informa que el margen no alcanza;
    - todo en CLP neto; el total con IVA se agrega al final.
    """
    # El más barato entre los productos iguales o equivalentes; uno solo "aproximado"
    # (otra marca o medida) se usa cuando no hay otro.
    por_linea, prioridad = {}, {}
    for m in mercado:
        precio = _numero(m.get("precio_unitario_neto"))
        if precio is None or precio <= 0:
            continue
        nota = (0 if m.get("coincidencia") in ("exacta", "equivalente") else 1, precio)
        linea = m.get("linea")
        if linea not in prioridad or nota < prioridad[linea]:
            por_linea[linea], prioridad[linea] = m | {"precio_unitario_neto": precio}, nota
    filas, costo_total, oferta_total, referencia_total = [], 0.0, 0.0, 0.0
    sin_precio = 0
    for item in items:
        cantidad = _numero(item.get("cantidad")) or 0.0
        mejor = por_linea.get(item.get("linea"))
        costo = mejor["precio_unitario_neto"] if mejor else None
        costo_gastos = costo * (1 + otros_costos) if costo is not None else None
        oferta = costo_gastos * (1 + margen) if costo_gastos is not None else None
        ref = _numero(item.get("ref_mediana"))
        if costo is None:
            sin_precio += 1
        else:
            costo_total += costo_gastos * cantidad
            oferta_total += oferta * cantidad
            if ref is not None:
                referencia_total += ref * cantidad
        filas.append({
            **item,
            "tienda": mejor.get("tienda") if mejor else None,
            "producto_mercado": mejor.get("producto_mercado") if mejor else None,
            "url": mejor.get("url") if mejor else None,
            "fecha_consulta": mejor.get("fecha_consulta") if mejor else None,
            "coincidencia": mejor.get("coincidencia") if mejor else None,
            "costo_unitario_neto": costo,
            "oferta_unitaria_neta": oferta,
            "subtotal_costo": costo_gastos * cantidad if costo_gastos is not None else None,
            "subtotal_oferta": oferta * cantidad if oferta is not None else None,
            "margen_vs_referencia": (ref / costo_gastos - 1) if (ref and costo_gastos) else None,
        })
    return {
        "items": filas,
        "items_sin_precio": sin_precio,
        "costo_neto": costo_total,
        "oferta_neta": oferta_total,
        "oferta_iva": oferta_total * IVA,
        "oferta_total": oferta_total * (1 + IVA),
        "utilidad": oferta_total - costo_total,
        "referencia_oc_neta": referencia_total or None,
        "margen": margen,
        "otros_costos": otros_costos,
    }
