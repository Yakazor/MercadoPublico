"""Evaluación comercial de las licitaciones: Excel, informes, GO / NO GO y correos.

Uso:
    python scripts/evaluar_licitaciones.py --items items.json --licitaciones licitaciones.json
    python scripts/evaluar_licitaciones.py ... --registrar entrada.json   # agrega una entrada al Claude Log

Lee:
    items.json, licitaciones.json            de la rama `datos` (los publica el radar)
    informes/mercado/<codigo>.json           precios de mercado (como scripts/presupuesto.py)
    informes/evaluacion/proveedores/<codigo>.json   proveedores encontrados por Claude (opcional)
    informes/evaluacion/claude_log.json      registro de análisis anteriores
Escribe en informes/evaluacion/:
    Licitaciones_evaluadas.xlsx   hojas «Licitaciones» (todas), «Evaluación» y «Claude Log»
    README.md                     resumen ejecutivo con las recomendaciones
    licitaciones/<codigo>_informe.md, _go_no_go.md y _correos.md   de las mejores N evaluadas
    claude_log.json               con una entrada nueva por corrida

Los supuestos de costos (despacho por región, horas, garantía, costo financiero) están
en config.yaml > evaluacion y se muestran en cada informe.
"""
import argparse
import json
import shutil
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import _ruta  # noqa: F401
from presupuesto import opciones_mercado
from radar.almacenamiento import texto_en_celda, texto_excel
from radar.config import cargar_config, hoy_chile, ruta_proyecto
from radar.evaluacion import NO_GO, evaluar, puntaje
from radar.plataforma import dias_al_cierre, supuestos_config
from radar.presupuesto import armar_presupuesto

URL_LICITACION = "https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion={}"
REMITENTE = {"empresa": "[Empresa]", "nombre": "[Nombre]", "cargo": "[Cargo]", "contacto": "[Contacto]"}
SIN_ADJUNTOS = "La API no entrega los adjuntos: están en la ficha, pestaña Anexos."


def clp(v) -> str:
    return "—" if v is None else "$" + f"{round(v):,}".replace(",", ".")


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f} %"


def celda(t) -> str:
    return " ".join(str(t or "").replace("|", "/").split())


def ficha(lic: dict) -> str:
    return lic.get("url") or URL_LICITACION.format(lic["codigo"])


def categoria(lic: dict, items: list[dict]) -> str:
    onu = Counter((i.get("categoria") or "").split(" / ")[0] for i in items if i.get("categoria"))
    partes = [lic.get("rubro_nombre")] + ([onu.most_common(1)[0][0]] if onu else [])
    return " · ".join(p for p in partes if p)


def observaciones(lic: dict, ev) -> str:
    obs = []
    if lic.get("tipo") == "Compra Ágil":
        obs.append("Compra Ágil: se cotiza el total con IVA y despacho")
        if lic.get("plazo_entrega_dias") is not None:
            obs.append(f"entrega en {lic['plazo_entrega_dias']:g} días")
        if lic.get("llamado") == 1:
            obs.append("primer llamado (solo empresas de menor tamaño)")
    if lic.get("alertas_regulatorias"):
        obs.append(f"ISP: {lic['alertas_regulatorias']}")
    if lic.get("dias_restantes") is not None and lic["dias_restantes"] <= 2:
        obs.append(f"cierra en {lic['dias_restantes']} día(s)")
    if ev:
        obs.append(f"{ev.decision} · riesgo {ev.riesgo.lower()}")
    return "; ".join(obs)


def respuesta_antes(lic: dict, hoy: date) -> date:
    """Dos días antes del cierre, sin pasar de hoy + 3 ni quedar antes de mañana."""
    cierre = date.fromisoformat((lic.get("fecha_cierre") or "")[:10]) if lic.get("fecha_cierre") else hoy + timedelta(5)
    return max(hoy + timedelta(1), min(cierre - timedelta(2), hoy + timedelta(3)))


def proveedores(codigo: str, mercado: dict, carpeta: Path) -> list[dict]:
    """Los que buscó Claude (con correo y contacto) o, si no hay, las tiendas del presupuesto."""
    archivo = carpeta / f"{codigo}.json"
    if archivo.exists():
        return json.loads(archivo.read_text(encoding="utf-8"))
    tiendas = {}
    for item in mercado.get("items") or []:
        for op in item.get("opciones") or []:
            if op.get("descartado") or not op.get("tienda"):
                continue
            t = tiendas.setdefault(op["tienda"], {"nombre": op["tienda"], "web": op.get("url"), "lineas": set()})
            t["lineas"].add(item.get("linea"))
    return [{"nombre": t["nombre"], "web": t["web"], "especialidad": f"Precio publicado para {len(t['lineas'])} línea(s)",
             "correo": None, "contacto": None, "fuente": "tienda del presupuesto (sin correo: confírmalo en su web)"}
            for t in sorted(tiendas.values(), key=lambda t: -len(t["lineas"]))][:5]


def detalle_resumido(p: dict, maximo: int = 15) -> list[str]:
    lineas = []
    for it in p["items"][:maximo]:
        cant = f"{it['cantidad']:g} {it.get('unidad') or ''}".strip() if it.get("cantidad") is not None else ""
        desc = celda(it.get("descripcion"))[:140]
        lineas.append(f"- {cant} — {celda(it.get('producto'))}" + (f": {desc}" if desc else ""))
    if len(p["items"]) > maximo:
        lineas.append(f"- … y {len(p['items']) - maximo} línea(s) más (detalle en la ficha).")
    return lineas


def go_no_go(lic: dict, ev) -> str:
    m, c = ev.margenes, ev.costos
    filas = [
        ("Licitación", f"[{lic['codigo']}]({ficha(lic)}) {celda(lic.get('nombre'))}"),
        ("Cliente", celda(lic.get("organismo"))),
        ("Monto estimado", clp(ev.ingresos["monto_estimado"])),
        ("Fecha de cierre", (lic.get("fecha_cierre") or "—")[:16]),
        ("Oferta sugerida (c/IVA)", clp(ev.ingresos["oferta_total"])),
        ("Margen esperado", f"{pct(m['neto_pct'])} neto · {pct(m['bruto_pct'])} bruto ({clp(m['neto'])} neto)"),
        ("Riesgo general", ev.riesgo),
        ("Complejidad", ev.complejidad),
        ("Factibilidad operativa", ev.factibilidad["operativa"]),
        ("Factibilidad financiera", ev.factibilidad["financiera"]),
        ("Factibilidad de plazos", ev.factibilidad["plazos"]),
        ("Probabilidad de adjudicación", f"{ev.probabilidad:.0%} (estimación heurística)"),
    ]
    lineas = [f"# GO / NO GO: {lic['codigo']}", "", f"## Resultado: {ev.etiqueta}", "",
              "| Indicador | Valor |", "|---|---|", *[f"| {k} | {v} |" for k, v in filas], "", "## Por qué", ""]
    lineas += [f"- {r}" for r in ev.razones]
    if ev.condiciones:
        lineas += ["", "## Condiciones para postular", "", *[f"- {x}" for x in ev.condiciones]]
    lineas += ["", f"Costo total estimado {clp(c['total'])} neto; punto de equilibrio {clp(m['equilibrio_total'])} "
                   "con IVA (oferta mínima que cubre todos los costos).", ""]
    return "\n".join(lineas)


def informe(lic: dict, p: dict, ev, provs: list[dict], s: dict) -> str:
    c, m, i = ev.costos, ev.margenes, ev.ingresos
    agil = lic.get("tipo") == "Compra Ágil"
    lineas = [
        f"# Informe ejecutivo: {celda(lic.get('nombre'))}", "",
        f"**{ev.recomendacion}** · {ev.etiqueta}", "",
        "## Resumen general", "",
        f"- **Licitación:** [{lic['codigo']}]({ficha(lic)}) ({lic.get('tipo') or '—'})",
        f"- **Organismo comprador:** {celda(lic.get('organismo'))} ({celda(lic.get('region'))})",
        f"- **Fecha de cierre:** {(lic.get('fecha_cierre') or '—')[:16]}",
        f"- **Monto referencial:** {clp(i['monto_estimado'])}",
        f"- **Ítems:** {len(p['items'])} ({ev.cobertura:.0%} con precio de mercado)",
        "",
        "## Análisis económico", "",
        "| Concepto | Monto (neto) |", "|---|---:|",
        f"| Costos directos (mercadería a precio de tienda) | {clp(c['directos'])} |",
        f"| Logística (despacho {pct(ev.supuestos['logistica_pct'])}, zona {ev.supuestos['zona']}) | {clp(c['logistica'])} |",
        f"| Horas hombre ({c['horas']:g} h × {clp(ev.supuestos['valor_hora'])}) | {clp(c['mano_obra'])} |",
        f"| Garantía de fiel cumplimiento | {clp(c['garantia'])} |",
        f"| Costo financiero (30 días hasta el pago) | {clp(c['financiero'])} |",
        f"| Subcontratación | {clp(c['subcontratacion'])} |",
        f"| **Costo total** | **{clp(c['total'])}** |",
        f"| Ingreso (oferta sugerida) | {clp(i['oferta_neta'])} |",
        f"| **Margen bruto** | {clp(m['bruto'])} ({pct(m['bruto_pct'])}) |",
        f"| **Margen neto** | {clp(m['neto'])} ({pct(m['neto_pct'])}) |",
        f"| Rentabilidad sobre costos | {pct(m['rentabilidad'])} |",
        f"| Punto de equilibrio (oferta mínima con IVA) | {clp(m['equilibrio_total'])} |",
        f"| Oferta sugerida con IVA{' y despacho' if agil else ''} | {clp(i['oferta_total'])} |",
        "",
        f"**Riesgos financieros:** {'; '.join(r for r in ev.riesgos if 'monto' in r or 'precio' in r) or 'sin riesgos financieros marcados'}.",
        "",
        "## Análisis operacional", "",
        f"- **Capacidad de cumplimiento:** factibilidad operativa {ev.factibilidad['operativa'].lower()}, complejidad {ev.complejidad.lower()}.",
        f"- **Recursos requeridos:** capital de trabajo de unos {clp(c['directos'] * 1.19)} con IVA para comprar la mercadería, "
        f"{c['horas']:g} horas de trabajo y transporte a {celda(lic.get('region'))}.",
        "- **Dependencias críticas:** stock y precio del proveedor al momento de la orden de compra; "
        "precios de tienda sin verificar hasta abrir cada link.",
        "- **Requisitos técnicos, garantías, experiencia y certificaciones:** están en las bases y anexos de la ficha "
        "(la API no los entrega). Revísalos antes de ofertar.",
        "",
        "## Análisis de plazos", "",
        f"- **Días para el cierre:** {lic.get('dias_restantes', '—')}"
        + (f" · **plazo de entrega:** {lic['plazo_entrega_dias']:g} días" if lic.get("plazo_entrega_dias") is not None else ""),
        f"- **Viabilidad:** {ev.factibilidad['plazos']}.",
        "- **Mitigación:** pedir cotización hoy (correos abajo), confirmar stock por escrito y tener un segundo proveedor.",
        "",
        "## Riesgos detectados", "", *([f"- {r}" for r in ev.riesgos] or ["- Ninguno marcado por las reglas automáticas."]),
        "",
        "## Proveedores recomendados", "",
        "| # | Proveedor | Especialidad | Correo | Sitio web | Contacto | Respuesta / entrega | Costo referencial |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for n, pr in enumerate(provs, 1):
        web = f"[web]({pr['web']})" if pr.get("web") else "—"
        tiempos = " / ".join(x for x in (pr.get("respuesta"), pr.get("entrega")) if x) or "por confirmar"
        lineas.append(f"| {n} | {celda(pr.get('nombre'))} | {celda(pr.get('especialidad'))} | {celda(pr.get('correo')) or 'por confirmar'} | "
                      f"{web} | {celda(pr.get('contacto')) or '—'} | {celda(tiempos)} | {celda(pr.get('costo_referencial')) or '—'} |")
    if not provs:
        lineas.append("| — | Sin proveedores todavía | | | | | | |")
    lineas += ["", "Prioridad: los que cubren más líneas primero. Riesgo: precios al detalle; pedir precio por volumen.",
               "", "## Conclusión ejecutiva", "", f"**{ev.recomendacion}.** " + " ".join(ev.razones)]
    if ev.condiciones:
        lineas += ["", "Condiciones:", *[f"- {x}" for x in ev.condiciones]]
    lineas += ["", "## Supuestos", "",
               f"Despacho por zona {s['logistica_pct']}; {s['horas_base']} h base + {s['horas_por_linea']} h por línea + "
               f"{s['horas_por_entrega']} h de entrega a {clp(s['valor_hora'])}/h; garantía {pct(s['garantia_pct'])} sobre "
               f"{s['garantia_desde_utm']} UTM (UTM {clp(s['utm'])}) con costo de emisión {pct(s['costo_emision_garantia_pct'])}; "
               f"costo financiero {s['tasa_financiera_mensual'] * 100:.1f} % mensual. Probabilidad de adjudicación: heurística. "
               "Se cambian en config.yaml > evaluacion.", ""]
    return "\n".join(lineas)


def correos(lic: dict, p: dict, provs: list[dict], remitente: dict, hoy: date) -> str:
    nombre = celda(lic.get("nombre"))
    plazo = respuesta_antes(lic, hoy).strftime("%d-%m-%Y")
    cuerpo = ["Nos encontramos evaluando nuestra participación en la siguiente licitación:", "",
              f"{nombre} ({lic['codigo']})", "",
              "Agradeceremos nos puedan enviar cotización considerando los siguientes requerimientos:", "",
              *detalle_resumido(p),
              "", "Asimismo, solicitamos indicar:", "", "- Valor neto.", "- Plazo de entrega.", "- Garantía ofrecida.",
              "- Vigencia de la oferta.", "- Condiciones de pago.", "",
              f"Idealmente requerimos respuesta antes del {plazo}.", "", "Quedamos atentos.", "", "Saludos cordiales,",
              remitente["empresa"], remitente["nombre"], remitente["cargo"], remitente["contacto"]]
    lineas = [f"# Borradores de correo: {lic['codigo']}", ""]
    for pr in provs or [{"nombre": "[Proveedor]"}]:
        lineas += [f"## {celda(pr.get('nombre'))}", "",
                   f"**Para:** {pr.get('correo') or '(correo por confirmar)'}  ",
                   f"**Asunto:** Solicitud de cotización – {nombre}", "", "```text",
                   f"Estimado/a {celda(pr.get('nombre'))},", "", *cuerpo, "```", ""]
    return "\n".join(lineas)


def excel(todas: list[tuple], evaluadas: list[tuple], log: list[dict], destino: Path) -> None:
    wb = Workbook()
    cab = PatternFill("solid", fgColor="1F3864")
    hojas = [
        ("Licitaciones", ["ID licitación", "Nombre", "Organismo comprador", "Monto estimado", "Fecha de publicación",
                          "Fecha de cierre", "Estado", "Región", "Categoría", "Tipo", "Enlace a la licitación",
                          "Enlace a bases administrativas", "Enlace a bases técnicas", "Enlace a anexos",
                          "Archivos asociados", "Observaciones"]),
        ("Evaluación", ["ID licitación", "Nombre", "Decisión", "Recomendación", "Ítems con precio", "Costos directos",
                        "Costos indirectos", "Costo total", "Oferta neta", "Oferta c/IVA", "Monto estimado",
                        "Margen bruto", "Margen bruto %", "Margen neto", "Margen neto %", "Punto de equilibrio c/IVA",
                        "Riesgo", "Complejidad", "Fact. operativa", "Fact. financiera", "Fact. plazos",
                        "Prob. adjudicación", "Riesgos detectados", "Condiciones"]),
        ("Claude Log", ["Fecha de análisis", "Autor", "Licitaciones procesadas", "Resultado del análisis",
                        "Riesgos detectados", "Decisiones tomadas", "Recomendaciones"]),
    ]
    filas = {
        "Licitaciones": [[l["codigo"], l.get("nombre"), l.get("organismo"), l.get("monto_estimado"),
                          (l.get("fecha_publicacion") or "")[:16], (l.get("fecha_cierre") or "")[:16], l.get("estado"),
                          l.get("region"), cat, l.get("tipo"), ficha(l), ficha(l), ficha(l), ficha(l), SIN_ADJUNTOS, obs]
                         for l, cat, obs in todas],
        "Evaluación": [[l["codigo"], l.get("nombre"), e.decision, e.recomendacion, f"{e.cobertura:.0%}",
                        e.costos["directos"], e.costos["indirectos"], e.costos["total"], e.ingresos["oferta_neta"],
                        e.ingresos["oferta_total"], e.ingresos["monto_estimado"], e.margenes["bruto"],
                        e.margenes["bruto_pct"], e.margenes["neto"], e.margenes["neto_pct"],
                        e.margenes["equilibrio_total"], e.riesgo, e.complejidad, e.factibilidad["operativa"],
                        e.factibilidad["financiera"], e.factibilidad["plazos"], e.probabilidad,
                        " · ".join(e.riesgos), " · ".join(e.condiciones)] for l, p, e in evaluadas],
        "Claude Log": [[x.get("fecha"), x.get("autor"), x.get("licitaciones_procesadas"), x.get("resultado"),
                        x.get("riesgos"), x.get("decisiones"), x.get("recomendaciones")] for x in reversed(log)],
    }
    dinero = {"Monto estimado", "Costos directos", "Costos indirectos", "Costo total", "Oferta neta", "Oferta c/IVA",
              "Margen bruto", "Margen neto", "Punto de equilibrio c/IVA"}
    porcentaje = {"Margen bruto %", "Margen neto %", "Prob. adjudicación"}
    enlaces = {"Enlace a la licitación", "Enlace a bases administrativas", "Enlace a bases técnicas", "Enlace a anexos"}
    wb.remove(wb.active)
    for nombre, columnas in hojas:
        ws = wb.create_sheet(nombre)
        ws.append(columnas)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF", name="Arial"), cab
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for fila in filas[nombre]:
            ws.append([texto_excel(v) for v in fila])
            for c in ws[ws.max_row]:          # aquí no hay fórmulas: todo es texto o número
                texto_en_celda(c)
        for j, col in enumerate(columnas, 1):
            letra = get_column_letter(j)
            ws.column_dimensions[letra].width = 14 if col in dinero | porcentaje else 40 if col in (
                "Nombre", "Riesgos detectados", "Condiciones", "Resultado del análisis", "Recomendaciones",
                "Observaciones", "Archivos asociados", "Riesgos detectados", "Decisiones tomadas") else 22
            for c in ws[letra][1:]:
                c.font = Font(name="Arial", size=10)
                if col in dinero:
                    c.number_format = '$#,##0;-$#,##0;"-"'
                elif col in porcentaje:
                    c.number_format = "0%"
                elif col in enlaces and c.value:
                    c.hyperlink, c.value = c.value, "Ver en la ficha" if col != "Enlace a la licitación" else c.value
                    c.font = Font(name="Arial", size=10, color="1D5FA8", underline="single")
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)


def resumen(evaluadas: list[tuple], seleccion: list[tuple], total: int, hoy: date) -> tuple[str, dict]:
    conteo = Counter(e.decision for _, _, e in evaluadas)
    lineas = ["# Evaluación comercial de licitaciones", "",
              f"Actualizado: {hoy.isoformat()}. {total} oportunidades vigentes en el Excel, {len(evaluadas)} con precios "
              f"de mercado evaluadas: {conteo.get('GO', 0)} GO, {conteo.get('GO CON CONDICIONES', 0)} GO con condiciones "
              f"y {conteo.get('NO GO', 0)} NO GO.", "",
              "- [Excel con todas las licitaciones, la evaluación y el Claude Log](Licitaciones_evaluadas.xlsx)", "",
              "## Recomendaciones para decidir", "",
              "| Licitación | Cierre | Oferta c/IVA | Monto estimado | Margen neto | Riesgo | Prob. | Decisión | Documentos |",
              "|---|---|---:|---:|---:|---|---:|---|---|"]
    for lic, p, e in seleccion:
        base = f"licitaciones/{lic['codigo']}"
        lineas.append(f"| [{lic['codigo']}]({ficha(lic)}) {celda(lic.get('nombre'))[:60]} | {(lic.get('fecha_cierre') or '—')[:10]} | "
                      f"{clp(e.ingresos['oferta_total'])} | {clp(e.ingresos['monto_estimado'])} | {pct(e.margenes['neto_pct'])} | "
                      f"{e.riesgo} | {e.probabilidad:.0%} | {e.etiqueta} | [informe]({base}_informe.md) · "
                      f"[GO/NO GO]({base}_go_no_go.md) · [correos]({base}_correos.md) |")
    accion = [f"- **{lic['codigo']}**: {e.etiqueta}. " + (e.condiciones[0] if e.condiciones else e.razones[0])
              for lic, _, e in seleccion if e.decision != NO_GO][:5]
    lineas += ["", "## Qué hacer ahora", "", *(accion or ["- Ninguna oportunidad pasa los criterios hoy."]),
               "", "Probabilidad de adjudicación: estimación heurística. Requisitos, garantías y certificaciones "
                   "se revisan en las bases de cada ficha.", ""]
    entrada = {
        "fecha": hoy.isoformat(), "autor": "Sistema (script)",
        "licitaciones_procesadas": f"{total} vigentes; {len(evaluadas)} evaluadas; informes de {len(seleccion)}",
        "resultado": f"{conteo.get('GO', 0)} GO, {conteo.get('GO CON CONDICIONES', 0)} con condiciones, {conteo.get('NO GO', 0)} NO GO",
        "riesgos": "; ".join(sorted({r.split(':')[0] for _, _, e in seleccion for r in e.riesgos}))[:500],
        "decisiones": "; ".join(f"{lic['codigo']}: {e.decision}" for lic, _, e in seleccion),
        "recomendaciones": " ".join(accion)[:800],
    }
    return "\n".join(lineas), entrada


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", required=True)
    ap.add_argument("--licitaciones", required=True)
    ap.add_argument("--mercado", default=str(ruta_proyecto("informes/mercado")))
    ap.add_argument("--salida", default=str(ruta_proyecto("informes/evaluacion")))
    ap.add_argument("--registrar", help="JSON con una entrada del Claude Log (fecha, licitaciones_procesadas, ...)")
    args = ap.parse_args()

    conf = cargar_config()
    s = supuestos_config(conf)
    remitente = REMITENTE | ((conf.get("evaluacion") or {}).get("remitente") or {})
    hoy = hoy_chile()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    ruta_log = salida / "claude_log.json"
    log = json.loads(ruta_log.read_text(encoding="utf-8")) if ruta_log.exists() else []

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    # Días al cierre contados desde hoy (los publicados pueden tener horas).
    lics = [l | {"dias_restantes": dias_al_cierre(l, hoy)}
            for l in json.loads(Path(args.licitaciones).read_text(encoding="utf-8"))]
    lics = [l for l in lics if l["dias_restantes"] is None or l["dias_restantes"] >= 0]
    por_codigo: dict[str, list[dict]] = {}
    for it in items:
        por_codigo.setdefault(it["codigo"], []).append(it)

    todas, evaluadas, mercados = [], [], {}
    for lic in sorted(lics, key=lambda l: l.get("fecha_cierre") or ""):
        archivo = Path(args.mercado) / f"{lic['codigo']}.json"
        ev = None
        if archivo.exists():
            mercado = json.loads(archivo.read_text(encoding="utf-8"))
            p = armar_presupuesto(por_codigo.get(lic["codigo"], []), opciones_mercado(mercado))
            if len(p["items"]) - p["items_sin_precio"] > 0:
                ev = evaluar(lic, p, s)
                evaluadas.append((lic, p, ev))
                mercados[lic["codigo"]] = mercado
        todas.append((lic, categoria(lic, por_codigo.get(lic["codigo"], [])), observaciones(lic, ev)))

    evaluadas.sort(key=lambda t: -puntaje(t[2]))
    seleccion = evaluadas[: s["max_evaluadas"]]
    carpeta = salida / "licitaciones"
    shutil.rmtree(carpeta, ignore_errors=True)
    carpeta.mkdir(parents=True)
    for lic, p, ev in seleccion:
        provs = proveedores(lic["codigo"], mercados[lic["codigo"]], salida / "proveedores")
        (carpeta / f"{lic['codigo']}_informe.md").write_text(informe(lic, p, ev, provs, s), encoding="utf-8")
        (carpeta / f"{lic['codigo']}_go_no_go.md").write_text(go_no_go(lic, ev), encoding="utf-8")
        (carpeta / f"{lic['codigo']}_correos.md").write_text(correos(lic, p, provs, remitente, hoy), encoding="utf-8")

    texto, entrada = resumen(evaluadas, seleccion, len(todas), hoy)
    # Una entrada automática por día (la de hoy se reemplaza); las de Claude se conservan.
    log = [x for x in log if not (x.get("autor") == "Sistema (script)" and x.get("fecha") == hoy.isoformat())]
    log.append(entrada)
    if args.registrar:
        nueva = json.loads(Path(args.registrar).read_text(encoding="utf-8"))
        log.append({"fecha": hoy.isoformat(), "autor": "Claude"} | nueva)
    ruta_log.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (salida / "README.md").write_text(texto, encoding="utf-8")
    excel(todas, evaluadas, log, salida / "Licitaciones_evaluadas.xlsx")
    print(f"{len(todas)} vigentes, {len(evaluadas)} evaluadas, {len(seleccion)} informes en {salida}")


if __name__ == "__main__":
    main()
