"""Versiones PDF de los informes de informes/ (índice, grupos y presupuestos).

Uso:
    python scripts/informes_pdf.py

Convierte cada .md a HTML (títulos, tablas, listas, citas, negrita y links) y lo
imprime a PDF horizontal con Chromium (Playwright) en informes/pdf/. Los links a
tiendas y a Mercado Público quedan activos en el PDF.
"""
import html
import re
import sys

CSS = """
@page { size: A4 %(orient)s; margin: 14mm 12mm 16mm 12mm; }
body { font-family: 'Liberation Sans', Arial, sans-serif; font-size: 9.5pt; color: #1b2430; line-height: 1.4; }
h1 { color: #1F3A5F; font-size: 17pt; margin: 0 0 8px; }
h2 { color: #1F3A5F; font-size: 12.5pt; margin: 16px 0 6px; border-bottom: 1px solid #c9d2de; padding-bottom: 3px; }
h3 { font-size: 10.5pt; margin: 12px 0 4px; }
table { border-collapse: collapse; width: 100%%; margin: 6px 0 10px; font-size: 8.3pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #1F3A5F; color: #fff; text-align: left; padding: 4px 5px; }
td { border: 1px solid #d5dce6; padding: 3px 5px; vertical-align: top; }
tr:nth-child(even) td { background: #f5f7fa; }
td.num, th.num { text-align: right; white-space: nowrap; }
blockquote { background: #FFF4DB; border-left: 4px solid #E0A800; margin: 8px 0; padding: 6px 10px; }
a { color: #1d5fa8; text-decoration: none; }
ul { margin: 4px 0 8px 18px; padding: 0; }
.pie { color: #5b6573; font-size: 8pt; margin-top: 14px; }
"""


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def celdas(linea):
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def convertir(md, titulo, orient):
    lineas = md.splitlines()
    out, i, en_lista = [], 0, False
    while i < len(lineas):
        l = lineas[i]
        if en_lista and not l.startswith("- "):
            out.append("</ul>"); en_lista = False
        if l.startswith("|") and i + 1 < len(lineas) and re.match(r"^\|[\s:|-]+\|$", lineas[i + 1].strip()):
            cab = celdas(l)
            alin = ["num" if a.strip().endswith(":") else "" for a in celdas(lineas[i + 1])]
            out.append("<table><thead><tr>" + "".join(
                f'<th class="{alin[k] if k < len(alin) else ""}">{inline(c)}</th>' for k, c in enumerate(cab)) + "</tr></thead><tbody>")
            i += 2
            while i < len(lineas) and lineas[i].startswith("|"):
                out.append("<tr>" + "".join(
                    f'<td class="{alin[k] if k < len(alin) else ""}">{inline(c)}</td>'
                    for k, c in enumerate(celdas(lineas[i]))) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        if l.startswith("### "): out.append(f"<h3>{inline(l[4:])}</h3>")
        elif l.startswith("## "): out.append(f"<h2>{inline(l[3:])}</h2>")
        elif l.startswith("# "): out.append(f"<h1>{inline(l[2:])}</h1>")
        elif l.startswith("> "): out.append(f"<blockquote>{inline(l[2:])}</blockquote>")
        elif l.startswith("- "):
            if not en_lista: out.append("<ul>"); en_lista = True
            out.append(f"<li>{inline(l[2:])}</li>")
        elif l.strip(): out.append(f"<p>{inline(l)}</p>")
        i += 1
    if en_lista: out.append("</ul>")
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(titulo)}</title>'
            f"<style>{CSS % {'orient': orient}}</style></head><body>" + "\n".join(out) +
            '<p class="pie">Radar de Licitaciones · Yakazor/MercadoPublico</p></body></html>')



import os

import _ruta  # noqa: F401
from radar.config import ruta_proyecto

PIE = ('<div style="font-size:7pt;color:#5b6573;width:100%;text-align:right;padding-right:12mm">'
       'Página <span class="pageNumber"></span> de <span class="totalPages"></span></div>')


def destinos() -> list[tuple]:
    base = ruta_proyecto("informes")
    pares = [(base / "README.md", "Indice_de_presupuestos"),
             (base / "grupos_licitaciones.md", "Grupos_de_licitaciones")]
    for md in sorted((base / "presupuestos").glob("*.md")):
        pares.append((md, f"Presupuesto_{md.stem}"))
    # Evaluación comercial: resumen, informe ejecutivo y hoja GO / NO GO (los correos quedan en .md).
    pares.append((base / "evaluacion" / "README.md", "Evaluacion_resumen"))
    for md in sorted((base / "evaluacion" / "licitaciones").glob("*.md")):
        if not md.stem.endswith("_correos"):
            pares.append((md, f"Evaluacion_{md.stem}"))
    return [(md, base / "pdf" / f"{nombre}.pdf") for md, nombre in pares if md.exists()]


def main():
    from playwright.sync_api import sync_playwright

    pares = destinos()
    if not pares:
        return
    pares[0][1].parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # CHROMIUM_PATH: usar un Chromium ya instalado en vez del de Playwright.
        navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        pagina = navegador.new_page()
        for md, pdf in pares:
            texto = md.read_text(encoding="utf-8")
            titulo = next((l[2:] for l in texto.splitlines() if l.startswith("# ")), "Informe")
            pagina.set_content(convertir(texto, titulo, "landscape"))
            pagina.pdf(path=str(pdf), format="A4", landscape=True, print_background=True,
                       display_header_footer=True, header_template="<span></span>", footer_template=PIE,
                       margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"})
            print(f"informes/pdf/{pdf.name}")
        navegador.close()


if __name__ == "__main__":
    main()
