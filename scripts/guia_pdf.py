"""Guía del Radar de Licitaciones (PDF para el usuario).

Uso: python3 scripts/guia_pdf.py informes/Guia_Radar_Licitaciones.pdf informes/guia/datos.json
(desde la raíz del repo). datos.json trae las cifras de la simulación del 17-10 (licitaciones, OC,
presupuestos) y las rutas de las capturas; el texto está aquí. Erratas: informes/Guia_erratas.md.
"""
import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, ListFlowable, ListItem, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

FUENTES = "/usr/share/fonts/truetype/liberation/"
pdfmetrics.registerFont(TTFont("Sans", FUENTES + "LiberationSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Sans-B", FUENTES + "LiberationSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Sans-I", FUENTES + "LiberationSans-Italic.ttf"))
pdfmetrics.registerFont(TTFont("Sans-BI", FUENTES + "LiberationSans-BoldItalic.ttf"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: E402
registerFontFamily("Sans", normal="Sans", bold="Sans-B", italic="Sans-I", boldItalic="Sans-BI")

AZUL = colors.HexColor("#1F3A5F")
AZUL_CLARO = colors.HexColor("#E8EEF6")
GRIS = colors.HexColor("#5B6573")
AMBAR = colors.HexColor("#FFF4DB")
AMBAR_BORDE = colors.HexColor("#E0A800")
VERDE = colors.HexColor("#E7F4EA")
VERDE_BORDE = colors.HexColor("#3C8D50")

base = ParagraphStyle("base", fontName="Sans", fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=5)
peq = ParagraphStyle("peq", parent=base, fontSize=8.5, leading=11.5, textColor=GRIS)
celda = ParagraphStyle("celda", parent=base, fontSize=8.5, leading=11, spaceAfter=0)
celda_b = ParagraphStyle("celda_b", parent=celda, fontName="Sans-B", textColor=colors.white)
h1 = ParagraphStyle("h1", parent=base, fontName="Sans-B", fontSize=17, leading=21, textColor=AZUL,
                    spaceBefore=4, spaceAfter=10)
h2 = ParagraphStyle("h2", parent=base, fontName="Sans-B", fontSize=12.5, leading=16, textColor=AZUL,
                    spaceBefore=10, spaceAfter=5)
h3 = ParagraphStyle("h3", parent=base, fontName="Sans-B", fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=3)
titulo = ParagraphStyle("titulo", parent=base, fontName="Sans-B", fontSize=28, leading=33, textColor=AZUL)
subtitulo = ParagraphStyle("subtitulo", parent=base, fontSize=13, leading=18, textColor=GRIS)


def p(texto, estilo=base):
    return Paragraph(texto, estilo)


def lista(items, numerada=False):
    return ListFlowable(
        [ListItem(p(t), leftIndent=12, value=i + 1 if numerada else None) for i, t in enumerate(items)],
        bulletType="1" if numerada else "bullet", start=1 if numerada else None,
        bulletFontName="Sans", bulletFontSize=9 if numerada else 7, leftIndent=14, bulletOffsetY=0 if numerada else -1)


def tabla(filas, anchos, encabezado=True, zebra=True):
    datos = [[p(str(c), celda_b if (encabezado and i == 0) else celda) for c in fila] for i, fila in enumerate(filas)]
    t = Table(datos, colWidths=anchos, repeatRows=1 if encabezado else 0)
    estilo = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D2DE")),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if encabezado:
        estilo.append(("BACKGROUND", (0, 0), (-1, 0), AZUL))
    if zebra:
        for i in range(1 if encabezado else 0, len(filas)):
            if i % 2 == 0:
                estilo.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F5F7FA")))
    t.setStyle(TableStyle(estilo))
    return t


def caja(contenido, fondo=AZUL_CLARO, borde=AZUL, ancho=17 * cm):
    filas = [[c] for c in contenido]
    t = Table(filas, colWidths=[ancho])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fondo), ("BOX", (0, 0), (-1, -1), 0.8, borde),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (0, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 7)]))
    return t


def aviso(texto):
    return caja([p(texto)], fondo=AMBAR, borde=AMBAR_BORDE)


def imagen(ruta, ancho):
    if not Path(ruta).exists():
        return Spacer(1, 1)
    img = Image(ruta)
    img.drawWidth, img.drawHeight = ancho, ancho * img.imageHeight / img.imageWidth
    return img


def pie(canvas, doc):
    canvas.saveState()
    canvas.setFont("Sans", 8)
    canvas.setFillColor(GRIS)
    canvas.drawString(2 * cm, 1.2 * cm, "Radar de Licitaciones · Guía de uso y de postulación a Mercado Público")
    canvas.drawRightString(19 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def clp(v):
    return "$" + f"{round(v):,}".replace(",", ".")


def construir(salida, d):
    hist = []

    # ---- Portada -----------------------------------------------------------
    hist += [Spacer(1, 3.5 * cm), p("Radar de Licitaciones", titulo),
             p("Cómo funciona, cómo usarlo y qué necesitas para venderle al Estado en Mercado Público", subtitulo),
             Spacer(1, 0.8 * cm),
             p(f"Versión final, después de las correcciones y la simulación completa · {d['fecha_larga']}. "
               "Revisada el 26 de octubre de 2026: EMT, giros del SII y erratas.", peq),
             Spacer(1, 1.2 * cm)]
    hist.append(caja([
        p("<b>En una frase</b>"),
        p("Cada día hábil el sistema descarga las licitaciones activas de Mercado Público, se queda con las de tus "
          "9 rubros, calcula qué precio pagó el Estado por productos parecidos y lo muestra en un dashboard. Ahí "
          "eliges qué licitaciones cotizar, buscas precios en tiendas chilenas y obtienes un presupuesto con tu "
          "margen e IVA, listo para decidir si postular."),
    ]))
    hist += [Spacer(1, 0.6 * cm), p("<b>Contenido</b>", h3)] + [p(t, ParagraphStyle("indice", parent=base, spaceAfter=2)) for t in [
        "1. Resumen y estado actual", "2. Cómo funciona por dentro", "3. Cómo usarlo día a día",
        "4. Presupuestos: cómo se calculan y cómo leerlos", "5. Rubros, grupos y cuándo agregar más",
        "6. Simulación completa: qué se probó y qué se corrigió",
        "7. Cómo postular a Mercado Público (persona natural o empresa, registro, ofertas, EMT y giros)",
        "8. Riesgos, garantías y productos regulados", "9. Plan de inicio y lista de verificación",
        "10. Mantención, límites y datos por confirmar"]]
    hist.append(PageBreak())

    # ---- 1. Resumen -------------------------------------------------------
    hist += [p("1. Resumen y estado actual", h1)]
    hist.append(tabla([
        ["Indicador", "Valor al cierre"],
        ["Licitaciones activas en Mercado Público", f"{d['activas']:,}".replace(",", ".")],
        ["Vigentes en tus 9 rubros (dashboard)", str(d["vigentes"])],
        ["Cierran en 7 días o menos", str(d["cierran_7"])],
        ["Ítems de licitaciones con cantidad y unidad (para presupuestar)", f"{d['items']:,}".replace(",", ".")],
        ["Productos con precio adjudicado (órdenes de compra)", f"{d['productos_precio']:,}".replace(",", ".")],
        ["Período de órdenes de compra", d["oc_rango"]],
        ["Presupuestos con precios de mercado", str(len(d["presupuestos"]))],
        ["Pruebas automáticas del código", f"{d['tests']} pasan"],
    ], [11 * cm, 6 * cm]))
    hist += [Spacer(1, 8), p("<b>Dónde está cada cosa</b>", h3), tabla([
        ["Qué", "Dónde"],
        ["Dashboard", "claude.ai/artifact/AUMtv926GXLeg1H82EDWrn (privado; puedes compartirlo)"],
        ["Código, configuración e informes", "github.com/Yakazor/MercadoPublico · rama feature/api-mercadopublico"],
        ["Datos publicados (JSON del dashboard)", "rama datos del mismo repositorio"],
        ["Presupuestos", "informes/presupuestos/&lt;código&gt;.md y .csv"],
        ["Precios de mercado encontrados", "informes/mercado/&lt;código&gt;.json (con fecha y link)"],
        ["Informe de grupos de licitaciones", "informes/grupos_licitaciones.md y .csv"],
        ["Esta guía", "informes/Guia_Radar_Licitaciones.pdf"],
        ["Instrucciones de la rutina automática", ".claude/RUTINA.md"],
    ], [5.5 * cm, 11.5 * cm])]
    hist.append(Spacer(1, 8))
    hist.append(aviso("<b>Lo más importante antes de postular:</b> el radar y los presupuestos son una herramienta "
                      "de decisión, no reemplazan leer las bases. Siempre revisa en la ficha de la licitación las "
                      "especificaciones, el plazo y lugar de entrega, las garantías y los criterios de evaluación."))
    hist.append(PageBreak())

    # ---- 2. Cómo funciona ---------------------------------------------------
    hist += [p("2. Cómo funciona por dentro", h1),
             p("El sistema tiene cuatro piezas que se pasan los datos en cadena. Todo corre en la nube: no "
               "necesitas tener tu computador encendido.")]
    flujo = [
        ["Paso", "Qué hace", "Cuándo"],
        ["1. API de Mercado Público", "Entrega las licitaciones activas, su detalle (ítems, cantidades, montos) y las "
         "órdenes de compra (OC) emitidas. Se consulta con tu ticket, que vive como secreto en GitHub "
         "(MP_TICKET) y nunca en el código.", "Siempre disponible"],
        ["2. GitHub Actions: radar", "Lista las ~5.000 licitaciones activas, filtra por nombre, pide el detalle de "
         "las candidatas (reutiliza las ya descargadas), clasifica por rubro y marca alertas ISP.",
         "Lunes a viernes 8:07 (hora de Chile) y al apretar «Actualizar ahora»"],
        ["3. GitHub Actions: órdenes de compra", "Descarga las OC de los últimos 21 días y calcula por producto el "
         "precio mínimo, mediana y máximo que pagó el Estado. Después rehace los presupuestos.",
         "Todos los días 6:11 y con «Actualizar ahora»"],
        ["4. Rama datos", "Los workflows publican licitaciones.json, items.json, precios.json y meta.json.", "Al "
         "terminar cada workflow"],
        ["5. Rutina de Claude", "Dispara los workflows, espera los datos, regenera los presupuestos, los guarda en el "
         "repositorio, te envía un resumen al teléfono y al final sube los datos al dashboard. Esa subida pide tu "
         "aprobación en la app de Claude (la plataforma no permite pre-autorizarla).",
         "Lunes a viernes 8:50 y con «Actualizar ahora»"],
        ["6. Dashboard", "Muestra licitaciones, precios y el simulador de presupuesto. Desde aquí eliges qué "
         "licitaciones cotizar.", "Cuando lo abras"],
    ]
    hist.append(tabla(flujo, [4 * cm, 9 * cm, 4 * cm]))
    hist += [p("Cómo decide si una licitación es de tus rubros", h2), lista([
        "<b>Palabras clave por rubro</b> (config.yaml): en el nombre, en los ítems que escribe el comprador y, para "
        "productos, en la clasificación ONU del ítem (sin su primer nivel, que mezcla rubros).",
        "<b>Exclusiones</b>: cada rubro descarta lo que no es reventa simple: arriendos, mantenciones, instalación, "
        "fabricación a medida, obras, servicios, y un grupo «clínico» común (implantes, medicamentos, GLP-1, "
        "traqueostomía, marcapasos, esterilización…).",
        "<b>Rubro principal</b>: gana el rubro que nombra lo que se compra («Uniformes y otros» con tablets en los "
        "ítems es Vestuario).",
        "<b>Alertas ISP</b>: guantes de látex, jeringas, N95, alcohol gel, desinfectantes y jabón de manos se "
        "marcan con un ícono de alerta; «solo regulados» indica que todo lo que se compra exige registro ISP.",
    ])]
    hist += [p("Respeto de los límites de la API", h2),
             p("Pausa de 2 segundos entre llamadas, reintentos con espera creciente (2, 4, 8 y 16 s) ante errores "
               "temporales y un solo proceso a la vez (todos los workflows comparten un grupo de concurrencia). Los "
               "detalles de licitación se guardan y solo se vuelven a pedir si cambió el cierre o pasaron 7 días; "
               "de las OC se usa una muestra estable por rubro y día.")]
    hist.append(PageBreak())

    # ---- 3. Uso -------------------------------------------------------------
    hist += [p("3. Cómo usarlo día a día", h1), p("Rutina sugerida (10 a 15 minutos al día)", h2), lista([
        "Abre el dashboard. Arriba ves cuántas licitaciones vigentes hay, cuántas cierran en 7 días y la fecha de "
        "los datos.",
        "En <b>Licitaciones</b> filtra por rubro, busca por palabra (no importan las tildes) y ordena por cierre o "
        "por monto. Cada fila trae el link a la ficha oficial.",
        "Marca las que te interesan con <b>Simular</b> (máximo 5 por vez) y aprieta <b>Buscar precios</b>. La "
        "rutina busca precios en tiendas chilenas solo para esas licitaciones, porque cada búsqueda cuesta tiempo "
        "y uso del plan. Tarda entre 10 y 30 minutos.",
        "Abre el <b>Simulador de presupuesto</b>: elige la licitación y ajusta el margen. Verás el costo, la oferta "
        "neta, el IVA, la utilidad y la comparación con lo que el Estado pagó y con el monto estimado.",
        "Si el número cierra, abre el informe en el repositorio (links a cada tienda), revisa las bases y prepara "
        "la oferta.",
    ], numerada=True)]
    hist += [p("Botones del dashboard", h2), tabla([
        ["Botón", "Qué hace", "Tiempo"],
        ["Actualizar ahora", "Fuerza la actualización completa: licitaciones, OC, presupuestos y dashboard. "
         "Ocurre sola de lunes a viernes a las 8:50. Al final te llega un aviso: abre la sesión «Rutina: Actualizar "
         "Radar de Licitaciones» en la app y aprueba la subida al dashboard.", "30 a 80 min"],
        ["Simular / Buscar precios", "Busca precios de mercado solo para las licitaciones elegidas y rehace sus "
         "presupuestos. Nunca corre solo.", "10 a 30 min"],
        ["Margen", "Recalcula la oferta al instante en el simulador (no cambia los informes del repositorio, que "
         "usan 20 %).", "Inmediato"],
    ], [3.6 * cm, 10.4 * cm, 3 * cm])]
    hist.append(Spacer(1, 6))
    hist.append(imagen(d["captura_licitaciones"], 10.5 * cm))
    hist.append(p("Vista de licitaciones del dashboard (datos de la simulación final).", peq))
    hist += [p("Power BI y Excel", h2),
             p("Si quieres tus propios análisis: los workflows dejan como artefacto en GitHub Actions los archivos "
               "licitaciones_actual y oc_items/oc_resumen_precios en CSV (separador «;», coma decimal y UTF-8, "
               "listos para la configuración es-CL) y Excel. También puedes correr el proyecto en tu computador "
               "(README, sección Instalación) con tu ticket en un archivo .env que nunca se sube al repositorio.")]
    hist.append(PageBreak())

    # ---- 4. Presupuestos ----------------------------------------------------
    hist += [p("4. Presupuestos: cómo se calculan y cómo leerlos", h1), tabla([
        ["Concepto", "Regla"],
        ["Precio de cada ítem", "La opción más barata de tiendas chilenas que sea el mismo producto o uno "
         "equivalente, convertida a neto (sin IVA) y a la unidad que pide la licitación. Las opciones solo "
         "aproximadas se usan si no hay otra."],
        ["Costo neto", "Suma de precio × cantidad + 5 % de otros costos (despacho, garantías, imprevistos)."],
        ["Oferta neta", "Costo neto × (1 + margen). Margen por defecto: 20 %."],
        ["IVA y total", "IVA 19 % sobre la oferta neta. En Compra Ágil se cotiza el total; en licitaciones, "
         "normalmente el neto unitario (lee las bases)."],
        ["Referencia OC", "Mediana de lo que el Estado pagó por el mismo producto ONU (o uno con ≥ 80 % de las "
         "palabras), solo en pesos. Si tu oferta la supera, es difícil ganar por precio."],
        ["Monto estimado", "Lo que el organismo declara que piensa gastar (no siempre lo publica)."],
    ], [3.5 * cm, 13.5 * cm])]
    hist += [p("Presupuestos de la simulación", h2)]
    filas = [["Licitación", "Rubro", "Ítems con precio", "Costo neto", "Oferta total", "Ref. OC (neto)", "Monto estimado"]]
    for pr in d["presupuestos"]:
        filas.append([f"{pr['codigo']}<br/>{pr['nombre'][:55]}", pr["rubro"], pr["con_precio"], clp(pr["costo_neto"]),
                      clp(pr["oferta_total"]), clp(pr["ref_oc"]) if pr.get("ref_oc") else "—",
                      clp(pr["monto_estimado"]) if pr.get("monto_estimado") else "—"])
    hist.append(tabla(filas, [4.4 * cm, 2.8 * cm, 1.6 * cm, 2 * cm, 2.1 * cm, 2 * cm, 2.1 * cm]))
    hist.append(Spacer(1, 6))
    for pr in d["presupuestos"]:
        if pr.get("lectura"):
            hist.append(p(f"<b>{pr['codigo']}:</b> {pr['lectura']}"))
    hist.append(aviso("Los precios de mercado vienen de resultados de búsqueda (las páginas .cl no se pueden abrir "
                      "desde la nube), así que se marcan como no verificados. Antes de ofertar, abre cada link, "
                      "confirma precio, stock y despacho, y pide cotización formal si el volumen es alto: en compras "
                      "por volumen el precio mayorista suele ser bastante menor que el de la tienda."))
    hist.append(Spacer(1, 6))
    hist.append(imagen(d["captura_simulador"], 14 * cm))
    hist.append(p("Simulador de presupuesto con una licitación cotizada.", peq))

    # ---- 5. Rubros y grupos ------------------------------------------------
    hist += [p("5. Rubros, grupos y cuándo agregar más", h1),
             p(f"El censo del {d['censo_fecha']} revisó {d['censo_muestra']:,} de {d['censo_activas']:,} licitaciones "
               f"activas: el radar detecta el {d['censo_pct']} de la muestra. Es bajo a propósito: la mayoría de las "
               "licitaciones son obras, servicios o medicamentos, que no son reventa simple.".replace(",", "."))]
    hist.append(tabla([["Rubro", "Vigentes"]] + [[r, str(n)] for r, n in d["por_rubro"]], [12 * cm, 5 * cm]))
    hist += [p("Grupos que podrías agregar", h2),
             p("Del informe <i>informes/grupos_licitaciones.md</i>, los segmentos de productos revendibles con más "
               "licitaciones que el radar casi no detecta. Para agregar uno se edita <i>config.yaml</i> (palabras clave y "
               "exclusiones): pídemelo en una conversación y lo hago con pruebas, igual que los 9 actuales.")]
    hist.append(tabla([["Segmento ONU", "Activas (est.)", "Detecta hoy", "Comentario"]] + d["grupos"],
                      [5.6 * cm, 2.2 * cm, 2 * cm, 7.2 * cm]))
    hist.append(PageBreak())

    # ---- 6. Simulación ------------------------------------------------------
    hist += [p("6. Simulación completa: qué se probó y qué se corrigió", h1),
             p("Se recorrió el flujo real de punta a punta: botón de actualización → rutina → workflows en GitHub → "
               "datos → presupuestos → dashboard, más una revisión del código con agentes independientes y una "
               "prueba de la página en un navegador (escritorio y teléfono de 360 px).")]
    hist.append(tabla([["Etapa", "Resultado"]] + d["etapas"], [5 * cm, 12 * cm]))
    hist += [p("Errores encontrados y corregidos", h2), lista(d["correcciones"])]
    hist.append(PageBreak())

    # ---- 7. Postular --------------------------------------------------------
    hist += [p("7. Cómo postular a Mercado Público", h1),
             aviso("<b>Sobre las fuentes:</b> esta sección resume una investigación con fuentes oficiales (Ley 19.886 "
                   "modificada por la Ley 21.634, Reglamento DS 661/2024, ChileCompra, SII, ChileAtiende) hecha en "
                   "octubre de 2026 y revisada por un segundo agente. Las páginas .cl no se pudieron abrir "
                   "directamente, así que los montos de 2026 (tarifas, UTM) deben confirmarse en el sitio oficial "
                   "antes de pagar o firmar. La sección de garantías no tuvo segunda revisión."),
             p("7.1 ¿Necesito crear una empresa?", h2),
             p("<b>No es obligatorio.</b> Una persona natural con inicio de actividades en el SII puede venderle al "
               "Estado (art. 4 de la Ley 19.886) y ninguna forma jurídica da puntaje extra. Lo obligatorio es: "
               "(1) inicio de actividades en el SII, exigido por los organismos públicos desde el 2-1-2026 "
               "(Ley 21.713), y (2) estar inscrito y <b>hábil</b> en el Registro de Proveedores ya al ofertar, "
               "incluso en Compra Ágil (desde el 12-12-2024).")]
    hist.append(tabla([
        ["", "Persona natural con giro", "SpA de un accionista (recomendada para reventa)", "EIRL / Ltda."],
        ["Responsabilidad", "Ilimitada: respondes con tus bienes por multas, garantías y deudas", "Limitada al aporte",
         "Limitada (Ltda. exige 2 socios)"],
        ["Costo de crearla", "$0 (inicio de actividades en línea)", "$0 en el Registro de Empresas y Sociedades + "
         "firma electrónica ($536 a $950) o notario", "Igual que SpA"],
        ["Impuestos", "Global Complementario sobre todo lo que ganes", "Pro Pyme General: 12,5 % en 2025-2027 "
         "(25 % general)", "Pro Pyme"],
        ["IVA en consultoría", "Boleta de honorarios exenta de IVA (retención 15,25 % en 2026)", "Debe cobrar 19 % de "
         "IVA", "Debe cobrar IVA"],
        ["Carga administrativa", "Baja", "Contabilidad, patente, F29 mensual, Declaración Jurada de beneficiarios "
         "finales en Mercado Público", "Igual; menos flexible"],
        ["Sumar socios después", "No aplica", "Fácil (venta o emisión de acciones)", "Requiere modificar estatutos"],
    ], [2.7 * cm, 4.3 * cm, 5.6 * cm, 4.4 * cm]))
    hist += [Spacer(1, 6), caja([
        p("<b>Recomendación para tu caso</b>"),
        p("Esquema mixto: una <b>SpA unipersonal para la reventa</b> (te protege de multas y cobro de garantías con "
          "bienes físicos, y la tasa Pro Pyme de 12,5 % permite reinvertir en inventario sin subir tu tramo de "
          "impuesto personal) y la <b>consultoría en control de gestión/BI como persona natural con boleta</b> "
          "mientras el volumen sea bajo, porque la boleta no lleva IVA y para un organismo público puede salir "
          "hasta 19 % más barata. Alternativa de costo mínimo: partir como persona natural con 1ª y 2ª categoría "
          "y crear la SpA cuando ganes las primeras compras."),
    ], fondo=VERDE, borde=VERDE_BORDE)]
    hist += [p("Antes de partir: tu situación laboral", h3), lista([
        "<b>Inhabilidad del art. 35 quáter:</b> ningún organismo puede comprarle a su propio personal, a sus "
        "cónyuges, convivientes civiles o parientes cercanos, ni a sociedades donde ellos participen. Si tu "
        "empleador (A-Impresores) es una empresa privada, tu empleo no te inhabilita; sí te afecta si un familiar "
        "directo trabaja en el organismo comprador.",
        "<b>Tu contrato de trabajo:</b> revisa cláusulas de exclusividad o de no competencia. El art. 160 N°2 del "
        "Código del Trabajo sanciona negociar dentro del giro del empleador si el contrato lo prohíbe. Como tu "
        "empleador es del rubro impresión, ofertar tóner, papel o impresos podría cruzarse con su giro: "
        "acláralo por escrito o deja esos productos fuera.",
        "<b>Deudas:</b> deudas tributarias sobre los límites legales o cotizaciones impagas te dejan inhábil.",
    ])]
    hist += [p("7.2 Crear la SpA (si eliges empresa)", h2), lista([
        "ClaveÚnica activa y cédula vigente.",
        "En <b>registrodeempresasysociedades.cl</b> → Constituir → SpA. Objeto social amplio: comercialización al "
        "por mayor y menor de insumos de aseo, artículos médicos no regulados, mobiliario, artículos de oficina, "
        "computación, ferretería, hogar, vestuario, deporte y material didáctico, y asesorías en gestión. Capital "
        "bajo (no hay mínimo legal; mantiene la patente en el mínimo). Firma con FEA en línea o ante notario "
        "(0,26 UF informado).",
        "Descarga gratis el estatuto y el certificado de vigencia; verifica el RUT asignado.",
        "Inicio de actividades en <b>sii.cl</b> (gratis). Códigos sugeridos: ver la tabla de la sección 7.5. Régimen: Pro Pyme "
        "General.",
        "Acredita domicilio (puede ser tu casa: certificado de dominio o contrato de arriendo que no prohíba "
        "actividad comercial).",
        "Certificado digital (~$15.000 + IVA al año) para el facturador electrónico gratuito del SII.",
        "Cuenta bancaria a nombre de la SpA (BancoEstado ofrece abrirla desde el mismo Registro en los primeros 30 "
        "días). No mezcles tu dinero personal con el de la empresa.",
        "Patente municipal en tu comuna: 2,5 a 5 por mil del capital propio, mínimo 1 UTM al año (~$72.000), en "
        "enero y julio.",
        "Cada mes: F29 antes del día 20, aunque no vendas. Cada año: F22 hasta el 30 de abril. Conviene un contador.",
    ], numerada=True)]
    hist += [p("7.3 Inscribirte y quedar hábil como proveedor", h2), lista([
        "Entra a <b>mercadopublico.cl</b> con ClaveÚnica, crea el usuario (gratis) y asocia la persona natural y/o "
        "la SpA (con su clave tributaria). Quedas como Administrador.",
        "Si es SpA, firma en línea la <b>Declaración Jurada del Registro de Proveedores</b> (socios, "
        "administradores y beneficiarios finales). Actualízala cada 6 meses o cuando algo cambie.",
        "Escritorio → Proveedores → Acreditación y habilidad: paga la acreditación. Valores 2025 para "
        "microempresa: $10.532 semestral o $20.010 anual (la plataforma muestra el valor 2026 antes de pagar).",
        "Espera el día hábil siguiente y confirma que la ficha diga <b>Hábil</b>. Si dice Inhábil, la pestaña "
        "Habilidad muestra el motivo.",
        "Completa la ficha (documentos, datos bancarios) e inscribe tus rubros con códigos ONU para recibir alertas.",
        "Renueva la acreditación antes de que venza: si vence, la ficha queda «Sin información» y no puedes ofertar.",
    ], numerada=True)]
    hist.append(PageBreak())
    hist += [p("7.4 Cómo ofertar", h2), tabla([
        ["Procedimiento", "Monto (UTM ≈ $72.151 oct-2026, por confirmar)", "Claves"],
        ["Compra Ágil", "Hasta 100 UTM ≈ $7,2 millones con IVA", "La mejor puerta de entrada. Primer llamado solo para "
         "empresas de menor tamaño. Publicada ≥ 24 h, sin bases ni garantías. Se cotiza el TOTAL con IVA y despacho "
         "y se deben cotizar todos los ítems."],
        ["Licitación L1", "Menos de 100 UTM", "≥ 5 días publicada. Normalmente sin garantías."],
        ["Licitación LE", "100 a menos de 1.000 UTM (≈ $7,2 a $72 millones)", "≥ 10 días (5 si es simple). "
         "Normalmente sin garantías; lee las bases."],
        ["Licitación LP", "1.000 a menos de 5.000 UTM", "≥ 20 días. Garantía de fiel cumplimiento (por regla "
         "general 5 %)."],
        ["Licitación LR", "5.000 UTM o más", "≥ 30 días. Fiel cumplimiento y, excepcionalmente, seriedad de la oferta "
         "(hasta 3 %)."],
        ["Convenio Marco", "Catálogo de ChileCompra", "Solo se entra ganando la licitación del convenio (ej. "
         "Ferretería 2239-5-LR26, ya cerrada). Para más adelante."],
    ], [3 * cm, 4.6 * cm, 9.4 * cm])]
    hist += [p("Paso a paso en una licitación", h3), lista([
        "Descarga bases y anexos y anota el cronograma (preguntas, cierre, adjudicación).",
        "Preguntas solo por el foro de la licitación y dentro del plazo. No contactes al organismo por otra vía.",
        "Completa los anexos en el formato pedido. En el formulario se ingresan precios NETOS y UNITARIOS, salvo que "
        "las bases digan otra cosa. Un precio poco claro deja la oferta inadmisible.",
        "Sube todo con tiempo (no a última hora) y guarda el comprobante.",
        "Si ganas: acepta la orden de compra (no hay plazo general: lo fijan las bases o la OC; regla práctica, 1 a "
        "2 días hábiles y siempre antes de entregar), entrega, consigue la «recepción conforme» y factura con el ID "
        "de la OC como referencia (tipo 801) y montos idénticos a la OC.",
        "Pago: 30 días corridos desde la factura (hasta 60 si las bases lo fundamentan). Si se atrasan, reclamo en "
        "ChileCompra con ClaveÚnica.",
        "Si un acto te parece ilegal o arbitrario: Tribunal de Contratación Pública dentro de 10 días hábiles.",
    ], numerada=True)]
    hist += [p("Costos de partida (referenciales)", h3), tabla([
        ["Concepto", "Monto"],
        ["Cuenta en Mercado Público y capacitaciones ChileCompra", "$0"],
        ["Acreditación Registro de Proveedores (microempresa)", "$20.010 al año o $10.532 semestral (valores 2025)"],
        ["Constituir la SpA", "$0 + firma electrónica $536 a $950 (o notario ~0,26 UF)"],
        ["Inicio de actividades y facturador del SII", "$0"],
        ["Certificado digital para facturar", "~$15.000 + IVA al año"],
        ["Patente municipal", "Mínimo 1 UTM al año (~$72.000)"],
        ["Contador", "Por cotizar"],
        ["<b>Total de partida aproximado (sin contador)</b>", "<b>~$110.000 el primer año</b>"],
    ], [10 * cm, 7 * cm])]
    hist.append(PageBreak())
    hist += [p("7.5 Empresa de Menor Tamaño (EMT) y giros del SII", h2),
             p("Las Compras Ágiles de <b>1er llamado</b> son solo para Empresas de Menor Tamaño (EMT); si nadie "
               "oferta, el organismo abre un <b>2º llamado</b> para cualquier proveedor. Mercado Público toma la "
               "marca EMT del SII, que la calcula con los ingresos por ventas declarados en la Operación Renta. "
               "Tu ficha de proveedor (pestaña Idoneidad) dice si clasificas."),
             caja([
                 p("<b>Tu situación al 26-10-2026</b>"),
                 p("Persona natural, tamaño «Sin información – renta anual 0 a 13,5 UTA»: el SII no tiene ventas "
                   "tuyas, así que <b>no clasificas como EMT</b> y no puedes cotizar en Compras Ágiles de 1er "
                   "llamado. Las licitaciones (L1, LE, LP, LR) no tienen esa restricción. El radar ya lo considera: "
                   "la rutina no cotiza Compras Ágiles de 1er llamado y la plataforma muestra de partida solo las "
                   "de 2º llamado (<font face='Courier'>compra_agil.soy_emt: false</font> en config.yaml)."),
             ], fondo=AMBAR, borde=AMBAR_BORDE),
             p("Cómo llegar a ser EMT", h3), lista([
                 "Agrega giros de venta de productos (tabla de abajo) en el SII. Esto no te hace EMT por sí solo, "
                 "pero sin un giro de comercio no deberías facturar la reventa.",
                 "Vende y emite boletas o facturas de esos giros (al Estado o a privados).",
                 "Declara esos ingresos en la Operación Renta (abril). La marca EMT se actualiza con esa "
                 "declaración, no al día siguiente de vender.",
                 "Confirma con la Mesa de Ayuda de ChileCompra (600 0061 211) cómo se clasifica una persona natural "
                 "sin ventas y si hay una vía más rápida; con una SpA nueva pasa lo mismo hasta su primera renta.",
             ], numerada=True),
             p("Giros sugeridos para tus rubros", h3),
             p("Agrégalos en <b>sii.cl → Servicios online → Peticiones administrativas y otras solicitudes → "
               "Actualización de información → Cambiar / ampliar giro o actividad económica</b>, con tu RUT y "
               "Clave Tributaria o ClaveÚnica. Plazo legal para informar un cambio: 2 meses. Busca cada código en el "
               "formulario y confirma la glosa antes de guardar.", peq)]
    hist.append(tabla([
        ["Código", "Glosa del SII (CIIU4.CL 2012)", "Rubros del radar"],
        ["469000", "Venta al por mayor no especializada", "Todos (el más importante)"],
        ["464904", "Venta al por mayor de artículos de papelería y escritorio", "Oficina y librería"],
        ["464905", "Venta al por mayor de libros", "Oficina y librería, didáctico"],
        ["465100", "Venta al por mayor de computadores, equipo periférico y programas informáticos",
         "Computación y electrónica"],
        ["464902", "Venta al por mayor de artículos eléctricos y electrónicos para el hogar", "Hogar y menaje"],
        ["464909", "Venta al por mayor de otros enseres domésticos n.c.p.", "Hogar y menaje, aseo, deporte"],
        ["464901", "Venta al por mayor de muebles, excepto muebles de oficina", "Mobiliario"],
        ["465904", "Venta al por mayor de maquinaria y equipo de oficina; muebles de oficina", "Mobiliario, oficina"],
        ["466302", "Venta al por mayor de materiales de construcción, artículos de ferretería, gasfitería y "
                   "calefacción", "Ferretería, construcción y eléctricos"],
        ["464100", "Venta al por mayor de productos textiles, prendas de vestir y calzado",
         "Vestuario, uniformes y EPP textil"],
        ["464908", "Venta al por mayor de instrumentos científicos y quirúrgicos",
         "Insumos médicos no regulados, laboratorio"],
        ["464903", "Venta al por mayor de artículos de perfumería, de tocador y cosméticos", "Aseo personal"],
        ["702000", "Actividades de consultoría de gestión", "Consultoría en gestión y BI"],
    ], [1.8 * cm, 10.2 * cm, 5 * cm]))
    hist += [Spacer(1, 6), aviso(
        "<b>Antes de agregarlos:</b> un giro de comercio es de 1ª categoría y va con IVA: emitirás facturas, "
        "declararás el F29 cada mes (aunque no vendas) y quizás necesites patente municipal. Revísalo con un "
        "contador. Para repuestos de vehículos, equipos de telecomunicaciones o venta por internet busca el código "
        "en el formulario del SII: no se pudo confirmar en una fuente oficial. Evita productos farmacéuticos "
        "(464907): requieren autorización del ISP.")]

    # ---- 8. Riesgos ---------------------------------------------------------
    hist += [p("8. Riesgos, garantías y productos regulados", h1), p("Garantías", h2), lista([
        "<b>Seriedad de la oferta:</b> asegura que mantendrás tu oferta y firmarás si ganas. Con el reglamento "
        "vigente se pide solo en licitaciones grandes y de forma excepcional.",
        "<b>Fiel cumplimiento:</b> la entrega quien gana; si entregas tarde o mal, la cobran además de multas o "
        "término anticipado. Obligatoria sobre 1.000 UTM.",
        "Instrumentos válidos: boleta bancaria, vale vista (inmoviliza el 100 %), póliza de garantía o certificado "
        "de fianza, siempre pagaderos a la vista e irrevocables. Errores típicos: glosa distinta, RUT del "
        "beneficiario equivocado, monto o vigencia insuficientes.",
    ])]
    hist += [p("Riesgos de revender", h2), lista([
        "<b>Stock:</b> pide disponibilidad por escrito antes de ofertar y ten un segundo proveedor. Si puedes, "
        "compra solo después de recibir la OC.",
        "<b>Precio:</b> tu oferta debe mantenerse durante la validez fijada en las bases; cuidado con productos "
        "importados y el dólar.",
        "<b>Plazo y despacho:</b> la entrega puede ser en otra región; incluye el flete en el costo (el 5 % de otros "
        "costos del presupuesto es una referencia, no un cálculo de flete).",
        "<b>Flujo de caja:</b> compras, entregas y te pagan 30 días después de la factura. Puedes ceder la factura "
        "en factoring (cotiza al menos 3 opciones).",
        "<b>Historial:</b> multas y términos anticipados quedan en tu ficha y restan puntos en futuras licitaciones.",
    ])]
    hist += [p("Productos regulados por el ISP", h2),
             p("El radar los marca con un ícono de alerta. Exigen registro sanitario, trazabilidad por lote y a veces bodega "
               "autorizada; las sanciones del Código Sanitario llegan a 1.000 UTM."),
             tabla([["Producto", "Exigencia"],
                    ["Guantes de látex / examen / quirúrgicos", "Registro ISP + conformidad por lote (DE 342/2004)"],
                    ["Jeringas y agujas", "Registro ISP + conformidad por lote (DE 47/2025)"],
                    ["Respiradores N95 / KN95", "EPP inscrito en el RFI del ISP (Res. 45/2023)"],
                    ["Alcohol gel", "Registro ISP como cosmético (Res. Minsal 199/2021)"],
                    ["Desinfectantes, cloro, amonio cuaternario", "Registro ISP «D» (DS 157)"],
                    ["Jabón de manos", "Producto de higiene con trámite ISP (DS 239/2002)"]], [7 * cm, 10 * cm]),
             Spacer(1, 6),
             p("Si solo revendes productos comprados en Chile al titular del registro, normalmente no necesitas tu "
               "propio registro, pero debes vender solo productos con registro vigente (registrosanitario.ispch.gob.cl) "
               "y guardar facturas y certificados por lote. <b>Recomendación:</b> parte con productos no regulados.")]
    hist.append(PageBreak())

    # ---- 9. Plan ------------------------------------------------------------
    hist += [p("9. Plan de inicio y lista de verificación", h1), p("Primeros 30 días", h2), tabla([
        ["Semana", "Acciones"],
        ["1", "Revisa contrato de trabajo y posibles inhabilidades. Decide estructura (SpA + boleta, o persona natural). "
         "Certificado de deuda en TGR."],
        ["2", "Constituye la SpA, inicio de actividades, certificado digital, cuenta bancaria. Patente en trámite."],
        ["3", "Cuenta en Mercado Público, Declaración Jurada, pago de acreditación, ficha Hábil, rubros ONU inscritos. "
         "Curso gratuito de ChileCompra «Cómo ofertar»."],
        ["4", "Usa el radar a diario. Cotiza 3 a 5 Compras Ágiles de aseo u oficina no regulados con proveedores "
         "confirmados. Simula en el dashboard cada licitación antes de ofertar."],
    ], [2 * cm, 15 * cm])]
    hist += [p("Antes de cada oferta", h2), lista([
        "La ficha del proveedor sigue Hábil.",
        "Leí las bases: especificaciones, cantidades, lugar y plazo de entrega, garantías, multas, criterios.",
        "Tengo precio, stock y plazo confirmados por escrito por mi proveedor.",
        "El presupuesto incluye flete, garantía y costo financiero de esperar 30 días el pago.",
        "Mi oferta está bajo la referencia OC y bajo el monto estimado (o sé por qué no).",
        "Los productos regulados tienen registro ISP vigente y certificados por lote.",
        "Ingresé precios netos unitarios (licitación) o total con IVA (Compra Ágil), según corresponda.",
        "Subí todos los anexos y guardé el comprobante.",
    ])]
    hist.append(PageBreak())

    # ---- 10. Mantención ----------------------------------------------------
    hist += [p("10. Mantención, límites y datos por confirmar", h1), lista([
        "<b>Ticket de la API:</b> si cambia, actualiza el secreto MP_TICKET en GitHub (Settings → Secrets and "
        "variables → Actions). Nunca lo pegues en el código ni en un mensaje.",
        "<b>Rutina:</b> corre en una sesión de Claude que usa tu plan. Si una actualización no publica datos, el "
        "resumen de la rutina dice por qué; también puedes ver los workflows en la pestaña Actions del repositorio. "
        "Mientras una aprobación quede pendiente, la sesión de la rutina queda en espera y el siguiente disparo no "
        "puede usarla: aprueba (o rechaza) la subida cuando llegue el aviso.",
        "<b>Datos sin dashboard:</b> aunque no apruebes la subida, la rama datos y los informes del repositorio sí "
        "quedan actualizados. También puedes pedirme en cualquier conversación «sube los datos al dashboard».",
        "<b>Precios de mercado:</b> no se verifican abriendo las tiendas; revisa cada link antes de ofertar.",
        "<b>Referencias OC:</b> la API no entrega la unidad de medida de las OC, así que la mediana puede mezclar "
        "precios por unidad y por caja. Úsala como orden de magnitud.",
        "<b>Clasificación:</b> puede haber falsos positivos o negativos. Si ves uno, dímelo y ajusto config.yaml con "
        "una prueba nueva.",
        "<b>Por confirmar en sitios oficiales:</b> tarifas 2026 del Registro de Proveedores, UTM de octubre de 2026, "
        "porcentajes de garantías en el DS 661, tasa Pro Pyme 12,5 % (Ley 21.755), y si ChileCompra trata como EMT a una "
        "persona natural sin ventas. Mesa de Ayuda de ChileCompra (confirmado): 600 0061 211 o 2 2595 0820, lunes "
        "a jueves de 08:30 a 17:30 y viernes de 08:30 a 16:30; el antiguo 600 7000 600 ya no corresponde.",
    ])]
    hist += [p("Fuentes principales", h2), lista([
        "Ley 19.886 y Ley 21.634 (bcn.cl) · Reglamento DS 661/2024 de Hacienda.",
        "ChileCompra: «Cómo convertirse en Proveedora y Proveedor del Estado 2025», «El Registro de Proveedores en "
        "Mercado Público 2025», «Cómo ofertar en Mercado Público 2025» (capacitacion.chilecompra.cl).",
        "ChileAtiende: fichas 547 (inscripción de proveedores) y 538 (Registro de Proveedores).",
        "SII: inicio de actividades, Circular 38/2025 (Ley 21.713), Circular 53/2025 (Pro Pyme), Oficio 1511/2022.",
        "Registro de Empresas y Sociedades (Ley 20.659) · DL 3.063 (patentes) · Ley 21.131 (pago a 30 días).",
        "ISP: DE 342/2004, DE 47/2025, Res. 45/2023, DS 157, DS 239/2002.",
    ])]

    doc = SimpleDocTemplate(salida, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=2 * cm, title="Radar de Licitaciones — Guía", author="Radar de Licitaciones",
                            subject="Funcionamiento, uso y postulación a Mercado Público")
    doc.build(hist, onFirstPage=pie, onLaterPages=pie)


if __name__ == "__main__":
    construir(sys.argv[1], json.load(open(sys.argv[2])))
