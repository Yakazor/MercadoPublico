"""Evaluación comercial de licitaciones: costos, márgenes, riesgo y decisión GO / NO GO.

Parte del presupuesto (`armar_presupuesto`: precios de mercado por ítem) y le suma lo
que una oferta real cuesta además de la mercadería: despacho según la región, horas de
trabajo, garantía de fiel cumplimiento y el costo financiero de esperar el pago. Todos
los supuestos están en `config.yaml > evaluacion` y se informan junto a cada resultado.

La probabilidad de adjudicación es una estimación heurística (precio frente al monto
estimado y a lo que el Estado pagó antes), no una predicción: sirve para ordenar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .filtro import normalizar
from .presupuesto import IVA

GO, CONDICIONADO, NO_GO = "GO", "GO CON CONDICIONES", "NO GO"
ETIQUETA = {GO: "🟢 GO (postular)", CONDICIONADO: "🟡 GO CON CONDICIONES", NO_GO: "🔴 NO GO"}
RECOMENDACION = {GO: "✅ ALTA RECOMENDACIÓN", CONDICIONADO: "🟡 RECOMENDACIÓN CONDICIONADA",
                 NO_GO: "🔴 NO RECOMENDADA"}

SUPUESTOS = {
    "utm": 72151,                      # CLP, octubre 2026 (por confirmar en sii.cl)
    "garantia_desde_utm": 1000,        # fiel cumplimiento por regla general sobre 1.000 UTM
    "garantia_pct": 0.05,              # 5 % del monto adjudicado
    "costo_emision_garantia_pct": 0.02,  # costo de la boleta o póliza sobre el monto garantizado
    "valor_hora": 6000,                # CLP por hora de trabajo propio
    "horas_base": 4,                   # preparar oferta, aceptar OC, facturar y cobrar
    "horas_por_linea": 0.25,           # cotizar y comprar cada línea
    "horas_por_entrega": 3,            # retirar y entregar
    "tasa_financiera_mensual": 0.015,  # costo de financiar la compra hasta el pago (30 días)
    "logistica_pct": {"cercana": 0.03, "media": 0.06, "lejana": 0.09, "extrema": 0.12},
    "max_evaluadas": 10,
}

# Zona logística desde Santiago (despacho como % del costo de la mercadería).
_ZONAS = {
    "cercana": ["metropolitana"],
    "media": ["valparaiso", "o'higgins", "libertador", "maule"],
    "lejana": ["coquimbo", "nuble", "biobio", "araucania", "atacama", "los rios"],
    "extrema": ["arica", "tarapaca", "antofagasta", "los lagos", "aysen", "magallanes"],
}


def zona_logistica(region: str | None) -> str:
    texto = normalizar(region or "")
    for zona, claves in _ZONAS.items():
        if any(normalizar(c) in texto for c in claves):
            return zona
    return "media"


def _nivel(puntos: int, bajo: int, medio: int) -> str:
    return "Bajo" if puntos <= bajo else ("Medio" if puntos <= medio else "Alto")


@dataclass
class Evaluacion:
    codigo: str
    decision: str
    costos: dict
    ingresos: dict
    margenes: dict
    riesgo: str
    riesgos: list[str]
    complejidad: str
    factibilidad: dict
    probabilidad: float
    cobertura: float
    condiciones: list[str] = field(default_factory=list)
    razones: list[str] = field(default_factory=list)
    supuestos: dict = field(default_factory=dict)

    @property
    def etiqueta(self) -> str:
        return ETIQUETA[self.decision]

    @property
    def recomendacion(self) -> str:
        return RECOMENDACION[self.decision]


def evaluar(lic: dict, p: dict, supuestos: dict | None = None) -> Evaluacion:
    """Evalúa una licitación con su presupuesto (`armar_presupuesto`)."""
    s = SUPUESTOS | (supuestos or {})
    n_items = len(p["items"])
    con_precio = n_items - p["items_sin_precio"]
    cobertura = con_precio / n_items if n_items else 0.0
    otros = p.get("otros_costos", 0.05)
    directo = p["costo_neto"] / (1 + otros) if p["costo_neto"] else 0.0
    oferta_neta, oferta_total = p["oferta_neta"], p["oferta_total"]
    monto = lic.get("monto_estimado") if lic.get("moneda") in (None, "CLP") else None
    dias = lic.get("dias_restantes")

    zona = zona_logistica(lic.get("region"))
    logistica = directo * s["logistica_pct"][zona]
    horas = s["horas_base"] + s["horas_por_linea"] * n_items + s["horas_por_entrega"]
    mano_obra = horas * s["valor_hora"]
    con_garantia = bool(monto and monto >= s["garantia_desde_utm"] * s["utm"])
    garantia = oferta_total * s["garantia_pct"] * s["costo_emision_garantia_pct"] if con_garantia else 0.0
    financiero = directo * (1 + IVA) * s["tasa_financiera_mensual"]
    indirectos = logistica + mano_obra + garantia + financiero
    total = directo + indirectos
    margen_bruto = oferta_neta - directo
    margen_neto = oferta_neta - total

    riesgos, puntos = [], 0
    if cobertura < 1:
        puntos += 2 if cobertura < 0.5 else 1
        riesgos.append(f"{n_items - con_precio} de {n_items} ítems sin precio de mercado: el costo real es mayor.")
    if p.get("lineas_globales"):
        puntos += 2
        riesgos.append("Líneas con unidad Global/Kit: la cantidad real está en las bases.")
    if con_precio and p.get("items_sin_verificar", 0) > con_precio / 2:
        puntos += 1
        riesgos.append("La mayoría de los precios no está verificada en la página de la tienda.")
    aproximadas = sum(1 for it in p["items"] if it.get("costo_unitario_neto") is not None
                      and it.get("coincidencia") not in ("exacta", "equivalente"))
    if aproximadas:
        puntos += 2 if aproximadas > con_precio / 2 else 1
        riesgos.append(f"{aproximadas} de {con_precio} precios son de productos aproximados (otra medida, marca o modelo).")
    if dias is not None and dias <= 5:
        puntos += 2 if dias <= 2 else 1
        riesgos.append(f"Cierra en {dias} día(s): poco tiempo para cotizar con proveedores.")
    plazo = lic.get("plazo_entrega_dias")
    if plazo is not None and plazo <= 2:
        puntos += 1
        riesgos.append(f"Plazo de entrega de {plazo:g} día(s): exige stock inmediato.")
    if zona in ("lejana", "extrema"):
        puntos += 1
        riesgos.append(f"Entrega en {lic.get('region')}: despacho caro y lento desde Santiago.")
    if monto and oferta_total > monto:
        puntos += 2
        riesgos.append(f"La oferta (${oferta_total:,.0f}) supera el monto estimado (${monto:,.0f}).".replace(",", "."))
    if lic.get("alertas_regulatorias"):
        puntos += 2
        riesgos.append(f"Productos con registro ISP: {lic['alertas_regulatorias']}.")
    if con_garantia:
        puntos += 1
        riesgos.append("Monto sobre 1.000 UTM: exige garantía de fiel cumplimiento (5 %).")
    riesgo = _nivel(puntos, 2, 5)

    complejidad_puntos = (0 if n_items <= 5 else 1 if n_items <= 20 else 2) + (1 if p.get("lineas_globales") else 0)
    complejidad = ("Baja", "Media", "Alta", "Alta")[complejidad_puntos]

    prob = 0.35
    if monto:
        razon = oferta_total / monto if monto else 1
        prob += 0.2 if razon <= 0.8 else 0.1 if razon <= 1 else -0.25
    if p.get("referencia_oc_neta") and p.get("oferta_con_referencia"):
        prob += 0.1 if p["oferta_con_referencia"] <= p["referencia_oc_neta"] else -0.1
    if cobertura < 1:
        prob -= 0.1
    if lic.get("tipo") == "Compra Ágil":
        prob -= 0.05   # suelen recibir muchas cotizaciones
    probabilidad = round(min(max(prob, 0.05), 0.8), 2)

    margen_neto_pct = margen_neto / oferta_neta if oferta_neta else -1.0
    factibilidad = {
        "operativa": "Alta" if complejidad == "Baja" and cobertura >= 0.8 else "Baja" if cobertura < 0.5 else "Media",
        "financiera": "Alta" if margen_neto_pct >= 0.10 else "Media" if margen_neto_pct >= 0 else "Baja",
        "plazos": "Sin dato" if dias is None else "Alta" if dias >= 5 else "Media" if dias >= 2 else "Baja",
    }

    razones, condiciones = [], []
    if dias is not None and dias < 1:
        razones.append("Cierra hoy o ya cerró: no hay tiempo para cotizar.")
    if lic.get("solo_regulados"):
        razones.append("Todo lo que se compra exige registro ISP.")
    if con_precio == 0:
        razones.append("Ningún ítem tiene precio de mercado: no se puede estimar el costo.")
    if con_precio and margen_neto < 0:
        razones.append("Con los costos indirectos el margen neto es negativo.")
    if monto and oferta_total > 1.3 * monto:
        razones.append("La oferta supera en más de 30 % el monto estimado.")
    if razones:
        decision = NO_GO
    else:
        if cobertura < 0.8:
            condiciones.append("Conseguir precio de los ítems que faltan antes de ofertar.")
        if p.get("lineas_globales"):
            condiciones.append("Revisar en las bases la cantidad real de las líneas globales.")
        if monto and oferta_total > monto:
            condiciones.append("Bajar costos (mayorista) o margen hasta quedar bajo el monto estimado.")
        if margen_neto_pct < 0.10:
            condiciones.append("Mejorar el margen neto (hoy bajo 10 %) negociando con proveedores.")
        if aproximadas:
            condiciones.append("Confirmar que los productos aproximados cumplen la especificación de las bases "
                               "(o cotizar el exacto).")
        if dias is not None and dias < 3:
            condiciones.append("Confirmar proveedor y stock hoy mismo (cierra en menos de 3 días).")
        if riesgo == "Alto":
            condiciones.append("Mitigar los riesgos marcados antes de comprometer la oferta.")
        if lic.get("alertas_regulatorias"):
            condiciones.append("Ofertar solo productos con registro ISP vigente y guardar certificados por lote.")
        decision = CONDICIONADO if condiciones else GO
        if decision == GO:
            razones.append(f"Margen neto de {margen_neto_pct:.0%}, precios para todos los ítems y riesgo {riesgo.lower()}.")
        else:
            razones.append("La oportunidad es rentable, pero depende de cumplir las condiciones indicadas.")

    return Evaluacion(
        codigo=lic.get("codigo"),
        decision=decision,
        costos={"directos": directo, "logistica": logistica, "mano_obra": mano_obra, "horas": horas,
                "garantia": garantia, "financiero": financiero, "indirectos": indirectos, "total": total,
                "subcontratacion": 0.0},
        ingresos={"oferta_neta": oferta_neta, "oferta_total": oferta_total, "monto_estimado": monto},
        margenes={"bruto": margen_bruto, "bruto_pct": margen_bruto / oferta_neta if oferta_neta else None,
                  "neto": margen_neto, "neto_pct": margen_neto / oferta_neta if oferta_neta else None,
                  "rentabilidad": margen_neto / total if total else None,
                  "equilibrio_neto": total, "equilibrio_total": total * (1 + IVA)},
        riesgo=riesgo,
        riesgos=riesgos,
        complejidad=complejidad,
        factibilidad=factibilidad,
        probabilidad=probabilidad,
        cobertura=cobertura,
        condiciones=condiciones,
        razones=razones,
        supuestos={"zona": zona, "logistica_pct": s["logistica_pct"][zona], "con_garantia": con_garantia,
                   "valor_hora": s["valor_hora"], "tasa_financiera_mensual": s["tasa_financiera_mensual"]},
    )


def puntaje(e: Evaluacion) -> float:
    """Para ordenar: decisión primero, luego utilidad esperada (margen × probabilidad)."""
    orden = {GO: 2, CONDICIONADO: 1, NO_GO: 0}[e.decision]
    return orden * 1e12 + max(e.margenes["neto"], 0) * e.probabilidad
