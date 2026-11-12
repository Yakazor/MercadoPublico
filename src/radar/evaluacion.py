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
# Con precio para menos de `cobertura_minima` de las líneas el margen sale de una parte del pedido:
# no hay decisión todavía (ni GO ni NO GO por margen), hay que conseguir los precios que faltan.
FALTA_PRECIO = "FALTA PRECIO"
DECISIONES = [GO, CONDICIONADO, FALTA_PRECIO, NO_GO]
ETIQUETA = {GO: "🟢 GO (postular)", CONDICIONADO: "🟡 GO CON CONDICIONES", FALTA_PRECIO: "⚪ FALTA PRECIO",
            NO_GO: "🔴 NO GO"}
RECOMENDACION = {GO: "✅ ALTA RECOMENDACIÓN", CONDICIONADO: "🟡 RECOMENDACIÓN CONDICIONADA",
                 FALTA_PRECIO: "⚪ SIN DECISIÓN: FALTAN PRECIOS", NO_GO: "🔴 NO RECOMENDADA"}

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
    # Sin crédito fiscal el IVA de las compras no se recupera: es costo, y el de la venta se
    # paga entero al SII.
    "recupera_iva_compras": False,
    # Bajo este % de líneas con precio no hay decisión (FALTA PRECIO).
    "cobertura_minima": 0.8,
    # Sin monto estimado, el techo es lo que el Estado pagó en OC parecidas, solo con referencias
    # precisas (5+ OC y precios parejos, `presupuesto.referencia_confiable`): NO GO si la oferta
    # de esas líneas lo supera en más de este %, con referencia precisa en al menos `referencia_minima`
    # de las líneas con precio.
    "tolerancia_sobre_oc": 0.20,
    "referencia_minima": 0.5,
}

# Tope del tipo de licitación en UTM (Ley de Compras): el organismo elige el tipo según su presupuesto,
# así que una oferta sobre el tope está fuera de lo que puede adjudicar. L1/E2: menos de 100 UTM;
# LE/CO: menos de 1.000; LP/B2: menos de 2.000; LQ/H2: menos de 5.000 (LR/I2: sin tope).
TOPE_TIPO_UTM = {"L1": 100, "E2": 100, "LE": 1000, "CO": 1000, "LP": 2000, "B2": 2000, "LQ": 5000, "H2": 5000}

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


def _miles(valor: float) -> str:
    """1234567.8 → «1.234.568» (sin tocar las comas del resto de la frase)."""
    return f"{valor:,.0f}".replace(",", ".")


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
    # costo_neto ya trae el IVA de las compras si no se recupera (armar_presupuesto con iva_es_costo).
    iva_compras = p.get("iva_compras") or 0.0
    directo = p["costo_neto"] / (1 + otros) - iva_compras if p["costo_neto"] else 0.0
    oferta_neta, oferta_total = p["oferta_neta"], p["oferta_total"]
    monto = lic.get("monto_estimado") if lic.get("moneda") in (None, "CLP") else None
    dias = lic.get("dias_restantes")

    zona = zona_logistica(lic.get("region"))
    logistica = directo * s["logistica_pct"][zona]
    horas = s["horas_base"] + s["horas_por_linea"] * n_items + s["horas_por_entrega"]
    mano_obra = horas * s["valor_hora"]
    # Sin monto publicado, la garantía depende de lo que se adjudique: se usa la oferta.
    con_garantia = (monto or oferta_total or 0) >= s["garantia_desde_utm"] * s["utm"]
    garantia = oferta_total * s["garantia_pct"] * s["costo_emision_garantia_pct"] if con_garantia else 0.0
    financiero = directo * (1 + IVA) * s["tasa_financiera_mensual"]
    indirectos = logistica + mano_obra + garantia + financiero
    total = directo + iva_compras + indirectos
    margen_bruto = oferta_neta - directo - iva_compras
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
    # Sin monto estimado hay dos techos: el tope legal del tipo de licitación y lo que el Estado pagó
    # en OC, solo con referencias precisas (una mediana de categoría amplia no es un techo).
    tope_utm = TOPE_TIPO_UTM.get(str(lic.get("tipo") or "").upper())
    tope_tipo = tope_utm * s["utm"] if tope_utm and not monto else None
    sobre_tipo = tope_tipo is not None and oferta_neta > tope_tipo
    con_referencia = p.get("lineas_con_referencia_confiable") or 0
    ref_oc, oferta_ref = p.get("referencia_confiable_neta"), p.get("oferta_con_referencia_confiable")
    techo_oc = None
    if not monto and con_precio and ref_oc and oferta_ref and con_referencia >= s["referencia_minima"] * con_precio:
        techo_oc = ref_oc * (1 + s["tolerancia_sobre_oc"])
    sobre_oc = techo_oc is not None and oferta_ref > techo_oc
    sin_techo = not monto and techo_oc is None
    if not monto:
        riesgos.append("Sin monto estimado publicado: " + (
            f"el techo es lo que el Estado pagó en OC parecidas (${_miles(ref_oc)} neto en "
            f"{con_referencia} línea(s) con referencia precisa)." if techo_oc is not None
            else "no hay una referencia precisa de OC con qué comparar la oferta"
            + (f"; el tipo {lic.get('tipo')} admite hasta {_miles(tope_utm)} UTM (${_miles(tope_tipo)})."
               if tope_tipo else ".")))
    if sobre_tipo:
        puntos += 2
        riesgos.append(f"La oferta neta (${_miles(oferta_neta)}) supera el tope del tipo de licitación "
                       f"({lic.get('tipo')}: hasta {_miles(tope_utm)} UTM, ${_miles(tope_tipo)}).")
    if sobre_oc:
        puntos += 2
        riesgos.append(f"La oferta de las líneas con referencia precisa (${_miles(oferta_ref)} neto) supera en "
                       f"{oferta_ref / ref_oc - 1:.0%} lo que el Estado pagó en OC parecidas.")
    if monto and oferta_total > monto:
        puntos += 2
        riesgos.append(f"La oferta (${_miles(oferta_total)}) supera el monto estimado (${_miles(monto)}): para entrar "
                       f"habría que comprar {'al menos ' if cobertura < 1 else ''}un {1 - monto / oferta_total:.0%} más "
                       "barato (pide precio de distribuidor).")
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
    if monto and oferta_total > monto:
        # Ofertar sobre el presupuesto del organismo casi nunca se adjudica (y sin crédito fiscal
        # no hay margen para bajar el precio).
        razones.append("La oferta supera el monto estimado del organismo.")
    if sobre_tipo:
        razones.append(f"Sin monto estimado, la oferta supera el tope del tipo de licitación ({lic.get('tipo')}: "
                       f"hasta {_miles(tope_utm)} UTM).")
    if sobre_oc:
        razones.append(f"Sin monto estimado, la oferta supera en más de {s['tolerancia_sobre_oc']:.0%} lo que el Estado "
                       "pagó en órdenes de compra parecidas.")
    if razones:
        decision = NO_GO
        if cobertura < 1:
            # Con las líneas que faltan el costo y la oferta solo suben: un NO GO por monto o techo sigue en pie.
            razones.append(f"Calculado con precio para {con_precio} de {n_items} líneas: con todas, el costo y la "
                           "oferta serían mayores.")
    elif cobertura < s["cobertura_minima"]:
        decision = FALTA_PRECIO
        condiciones.append(f"Conseguir precio de las {n_items - con_precio} líneas que faltan: con {con_precio} de "
                           f"{n_items} el margen sale de una parte del pedido.")
        razones.append(f"Hay precio para {cobertura:.0%} de las líneas (mínimo {s['cobertura_minima']:.0%}): "
                       "todavía no se puede decidir.")
    else:
        if cobertura < 1:
            condiciones.append("Conseguir precio de los ítems que faltan antes de ofertar.")
        if sin_techo:
            condiciones.append("Sin monto estimado ni referencia precisa de OC: revisar en las bases el presupuesto "
                               "disponible antes de ofertar.")
        if p.get("lineas_globales"):
            condiciones.append("Revisar en las bases la cantidad real de las líneas globales.")
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
        costos={"directos": directo, "iva_compras": iva_compras, "logistica": logistica, "mano_obra": mano_obra, "horas": horas,
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
    orden = {GO: 3, CONDICIONADO: 2, FALTA_PRECIO: 1, NO_GO: 0}[e.decision]
    return orden * 1e12 + max(e.margenes["neto"], 0) * e.probabilidad
