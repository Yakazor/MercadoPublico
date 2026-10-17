"""Informe de grupos de licitaciones: todos los segmentos ONU vs los rubros del radar.

Uso:
    python scripts/informe_grupos.py --censo censo.json [--licitaciones licitaciones.json]

Escribe informes/grupos_licitaciones.md y .csv: cada segmento del clasificador ONU
que usa Mercado Público, cuántas licitaciones activas tiene (estimado a partir del
censo), su monto, qué parte detecta hoy el radar y con qué rubro, y una orientación
de si se puede comprar y revender sin grandes permisos. Sirve para decidir si
agregar rubros a config.yaml.
"""
import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

import _ruta  # noqa: F401
from radar.config import cargar_config, ruta_proyecto

# Segmentos del clasificador ONU (UNSPSC) y orientación para un revendedor que parte.
# "sí": productos que se compran y revenden sin permisos especiales; "parcial": una
# parte sí (o exige algún registro); "no": servicios, obras, permisos sanitarios o
# técnicos mayores. Es una guía: revisa cada licitación.
SEGMENTOS = {
    "10": ("Material vivo vegetal y animal", "no", "Plantas y animales vivos: permisos SAG."),
    "11": ("Material mineral, textil, vegetal y animal no comestible", "parcial", "Materias primas; algunas con trazabilidad."),
    "12": ("Material químico, bioquímicos y gases", "parcial", "Químicos y gases: sustancias peligrosas (DS 43) y transporte."),
    "13": ("Resinas, caucho, espumas, películas y elastómeros", "sí", "Plásticos, mangueras, espumas."),
    "14": ("Papel y materiales de papel", "sí", "Papel, cartón, envases de papel."),
    "15": ("Combustibles, lubricantes y anticorrosivos", "parcial", "Combustibles exigen autorización SEC; lubricantes no."),
    "20": ("Maquinaria y accesorios de minería y perforación", "no", "Equipos técnicos con servicio y certificaciones."),
    "21": ("Maquinaria agrícola, pesquera, forestal y de jardinería", "parcial", "Herramientas y equipos de jardín sí; maquinaria pesada no."),
    "22": ("Maquinaria para construcción y edificación", "parcial", "Equipos menores sí; maquinaria pesada no."),
    "23": ("Maquinaria y accesorios industriales", "parcial", "Depende del equipo y su instalación."),
    "24": ("Manejo, acondicionamiento y almacenamiento de materiales", "sí", "Carros, estanterías, contenedores, cajas."),
    "25": ("Vehículos y sus accesorios y componentes", "parcial", "Repuestos y accesorios sí; vehículos exigen concesionario."),
    "26": ("Maquinaria para generación y distribución de energía", "parcial", "Baterías, generadores menores; instalación certificada SEC."),
    "27": ("Herramientas y maquinaria general", "sí", "Ferretería y herramientas."),
    "30": ("Componentes y suministros para construcción y obras civiles", "sí", "Materiales de construcción (sin la obra)."),
    "31": ("Componentes y suministros de fabricación", "sí", "Pinturas, tornillos, adhesivos, ferretería industrial."),
    "32": ("Componentes y suministros electrónicos", "parcial", "Componentes electrónicos; poco volumen de reventa."),
    "39": ("Sistemas eléctricos e iluminación", "sí", "Ampolletas, luminarias, cables, extensiones."),
    "40": ("Distribución y acondicionamiento (climatización, fluidos)", "parcial", "Equipos sí; instalación de gas o clima exige técnicos SEC."),
    "41": ("Equipos de laboratorio, medición y pruebas", "parcial", "Instrumentos simples sí; equipos calibrados con servicio no."),
    "42": ("Equipo médico, accesorios y suministros", "parcial", "Insumos no regulados sí; dispositivos con registro ISP no."),
    "43": ("Tecnologías de la información y telecomunicaciones", "sí", "Computadores, periféricos, accesorios (licencias exigen partner)."),
    "44": ("Equipos de oficina, accesorios y suministros", "sí", "Útiles de oficina, tóner, papelería."),
    "45": ("Impresión, fotografía y audiovisuales", "sí", "Proyectores, cámaras, audio."),
    "46": ("Defensa, orden público, protección y seguridad", "parcial", "EPP y señalética sí; armamento y equipos tácticos no."),
    "47": ("Equipos de limpieza y suministros", "sí", "Aseo y limpieza (desinfectantes con registro ISP: marcar)."),
    "48": ("Maquinaria y suministros para la industria de servicios", "sí", "Equipamiento de cocina, gastronomía, lavandería."),
    "49": ("Deportes, recreación y ocio", "sí", "Artículos deportivos y de recreación."),
    "50": ("Alimentos, bebidas y tabaco", "parcial", "Exige resolución sanitaria de bodega y transporte (Seremi)."),
    "51": ("Medicamentos y productos farmacéuticos", "no", "Exige farmacia o droguería autorizada por el ISP."),
    "52": ("Artículos domésticos y electrónica de consumo", "sí", "Electrodomésticos, menaje, ropa de cama."),
    "53": ("Ropa, maletas y productos de aseo personal", "sí", "Vestuario, calzado, mochilas, artículos de tocador."),
    "54": ("Relojería, joyería y piedras preciosas", "sí", "Relojes, galvanos, premios."),
    "55": ("Publicaciones impresas y electrónicas", "sí", "Libros, revistas (algunas solo por editoriales)."),
    "56": ("Muebles, mobiliario y decoración", "sí", "Mobiliario de oficina, escolar y decoración."),
    "60": ("Instrumentos musicales, juegos, juguetes, artes y equipo educativo", "sí", "Juguetes, material didáctico, instrumentos."),
    "70": ("Servicios agrícolas, pesqueros, forestales y de fauna", "no", "Servicio."),
    "71": ("Servicios de minería, petróleo y gas", "no", "Servicio."),
    "72": ("Servicios de edificación, construcción y mantenimiento", "no", "Obras y mantención: no es reventa."),
    "73": ("Servicios de producción industrial y manufactura", "no", "Servicio."),
    "76": ("Servicios de limpieza industrial", "no", "Servicio de aseo (no es venta de productos)."),
    "77": ("Servicios medioambientales", "no", "Servicio."),
    "78": ("Servicios de transporte, almacenaje y correo", "no", "Servicio."),
    "80": ("Servicios de gestión, profesionales y administrativos", "parcial", "Consultoría: es tu rubro de servicios (control de gestión/BI)."),
    "81": ("Servicios de ingeniería, investigación y tecnología", "no", "Servicio profesional (salvo BI/software si lo prestas)."),
    "82": ("Servicios editoriales, de diseño y artes gráficas", "no", "Servicio (imprenta, diseño)."),
    "83": ("Servicios públicos y relacionados", "no", "Agua, luz, telefonía."),
    "84": ("Servicios financieros y de seguros", "no", "Servicio regulado."),
    "85": ("Servicios de salud", "no", "Prestaciones de salud."),
    "86": ("Servicios educativos y de formación", "parcial", "Capacitación: posible si la prestas tú (OTEC/Sence aparte)."),
    "90": ("Servicios de viajes, alimentación, alojamiento y entretenimiento", "no", "Servicio (catering, pasajes, eventos)."),
    "91": ("Servicios personales y domésticos", "no", "Servicio."),
    "92": ("Servicios de defensa, orden público y seguridad", "no", "Servicio de guardias y vigilancia."),
    "93": ("Servicios políticos y de asuntos cívicos", "no", "Servicio."),
    "94": ("Organizaciones y clubes", "no", "Membresías."),
    "95": ("Terrenos, edificios, estructuras y vías", "no", "Arriendo o compra de inmuebles."),
}


def _n(valor) -> str:
    return f"{valor:,}".replace(",", ".")


def _guia(codigo: str, nombre: str | None) -> tuple:
    """Orientación del segmento. Mercado Público usa el código 10 también para su
    categoría propia «Consultoria», que no es «Material vivo vegetal y animal»."""
    if nombre and "consultor" in nombre.lower():
        return (nombre, "parcial", "Consultorías: tu rubro de servicios si son de gestión, control de gestión o BI.")
    return SEGMENTOS.get(codigo, (None, "?", ""))


def _clp(valor) -> str:
    return "—" if valor is None or pd.isna(valor) else "$" + f"{round(valor):,}".replace(",", ".")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--censo", required=True, help="censo.json de la rama censo")
    ap.add_argument("--licitaciones", help="licitaciones.json de la rama datos (vigentes por rubro hoy)")
    ap.add_argument("--salida", default=str(ruta_proyecto("informes/grupos_licitaciones.md")))
    args = ap.parse_args()

    censo = json.loads(Path(args.censo).read_text(encoding="utf-8"))
    config = cargar_config()
    rubros = config.get("rubros") or {}
    vigentes = Counter()
    if args.licitaciones:
        vigentes = Counter(l.get("rubro") for l in json.loads(Path(args.licitaciones).read_text(encoding="utf-8")))

    observados = {s["codigo"]: s for s in censo["segmentos"]}
    filas = []
    for codigo in sorted(set(SEGMENTOS) | set(observados)):
        s = observados.get(codigo, {})
        guia = _guia(codigo, s.get("segmento"))
        filas.append({
            "codigo": codigo,
            "segmento": s.get("segmento") or guia[0] or "Sin categoría",
            "licitaciones_muestra": s.get("licitaciones", 0),
            "porcentaje": s.get("porcentaje", 0.0),
            "estimado_activas": s.get("estimado_activas", 0),
            "monto_clp_estimado": s.get("monto_clp_estimado", 0),
            "detectadas_radar": s.get("detectadas", 0),
            "cobertura_radar": s.get("cobertura", 0.0),
            "rubros_radar": ", ".join(f"{rubros.get(r, {}).get('nombre', r)} ({n})" for r, n in (s.get("rubros") or {}).items()),
            "reventa": guia[1],
            "orientacion": guia[2],
            "familias": "; ".join(f"{f['familia']} ({f['licitaciones']})" for f in (s.get("familias") or [])[:6]),
            "ejemplos": " | ".join(s.get("ejemplos") or []),
        })
    tabla = pd.DataFrame(filas).sort_values(["licitaciones_muestra", "codigo"], ascending=[False, True])

    procesadas = censo["procesadas"]
    lineas = [
        "# Grupos de licitaciones: todos los segmentos vs los rubros del radar",
        "",
        f"Censo del {censo.get('generado', '')[:10]}: se revisó el detalle de {_n(procesadas)} de las "
        f"{_n(censo['activas_total'])} licitaciones activas (muestra estable al azar). Cada licitación cuenta en "
        "cada segmento del clasificador ONU que compra; los estimados escalan la muestra al total.",
        "",
        f"El radar, con los {len(rubros)} rubros de config.yaml, detecta {_n(censo['detectadas_por_el_radar'])} de las "
        f"{_n(procesadas)} licitaciones de la muestra "
        f"({str(round(100 * censo['detectadas_por_el_radar'] / max(procesadas, 1), 1)).replace('.', ',')} %)" + ". Ojo: la mayoría "
        "de las licitaciones son de servicios, obras o medicamentos, que el radar deja fuera a propósito.",
        "",
        "## Tus rubros en el dashboard",
        "",
        "| Rubro | Palabras clave | Vigentes hoy |",
        "|---|---:|---:|",
    ]
    for clave, datos in rubros.items():
        lineas.append(f"| {datos.get('nombre', clave)} | {len(datos.get('palabras_clave') or [])} | {vigentes.get(clave, 0)} |")

    def tabla_md(df, titulo, nota):
        out = ["", f"## {titulo}", "", nota, "",
               "| Segmento ONU | Licitaciones activas (estimado) | % | Monto estimado | Detecta el radar | Rubros que lo cubren | ¿Reventa? | Orientación |",
               "|---|---:|---:|---:|---:|---|---|---|"]
        for f in df.itertuples(index=False):
            out.append(f"| {f.codigo} {f.segmento} | {_n(f.estimado_activas)} | {f.porcentaje:.1f} | {_clp(f.monto_clp_estimado)} | "
                       f"{f.cobertura_radar:.0f} % | {f.rubros_radar or '—'} | {f.reventa} | {f.orientacion} |".replace(".", ",", 1) if False else
                       f"| {f.codigo} {f.segmento} | {_n(f.estimado_activas)} | {str(f.porcentaje).replace('.', ',')} | {_clp(f.monto_clp_estimado)} | "
                       f"{f.cobertura_radar:.0f} % | {f.rubros_radar or '—'} | {f.reventa} | {f.orientacion} |")
        return out

    con = tabla[tabla["licitaciones_muestra"] > 0]
    candidatos = con[(con["reventa"].isin(["sí", "parcial"])) & (con["cobertura_radar"] < 50)]
    lineas += tabla_md(candidatos, "Grupos que podrías agregar",
                       "Segmentos de productos revendibles con licitaciones activas que el radar casi no detecta "
                       "(menos del 50 %). Son los candidatos a nuevos rubros o a más palabras clave.")
    lineas += tabla_md(con, "Todos los grupos con licitaciones activas",
                       "Ordenados por cantidad de licitaciones. «Detecta el radar» es la parte de ese segmento que hoy "
                       "entra al dashboard.")
    sin = tabla[tabla["licitaciones_muestra"] == 0]
    if len(sin):
        lineas += ["", "## Segmentos sin licitaciones en la muestra", "",
                   ", ".join(f"{f.codigo} {f.segmento}" for f in sin.itertuples(index=False)) + "."]
    lineas += ["", "## Familias principales por segmento", ""]
    for f in con.itertuples(index=False):
        if f.familias:
            lineas.append(f"- **{f.codigo} {f.segmento}:** {f.familias}")
    lineas += ["", "_Generado con `scripts/informe_grupos.py` a partir del censo (`scripts/censo_rubros.py`, "
                   f"workflow «Censo de grupos de licitaciones»). Actualizado: {date.today().isoformat()}._", ""]
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text("\n".join(lineas), encoding="utf-8")
    tabla.to_csv(salida.with_suffix(".csv"), sep=";", decimal=",", index=False, encoding="utf-8-sig")
    print(f"{salida} ({len(con)} segmentos con licitaciones, {len(candidatos)} candidatos)")


if __name__ == "__main__":
    main()
