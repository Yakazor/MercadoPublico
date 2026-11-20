"""Estilo visual de la plataforma: marketplace B2B claro (fondos pastel, tarjetas blancas de esquinas
redondeadas, etiquetas en píldora, un solo color de acción y números grandes).

Los colores y letras base están en `.streamlit/config.toml` ([theme]); aquí va lo que Streamlit no
configura: encabezado con degradado, caja de indicadores, tarjetas de oportunidad y etiquetas. Todo
texto que viene de los datos pasa por `html.escape` antes de ir al HTML.
"""
from html import escape

import pandas as pd
import streamlit as st

import comun
from radar.evaluacion import CONDICIONADO, FALTA_PRECIO, GO, NO_GO
from radar.plataforma import es_compra_agil, es_nueva, monto_referencial, solo_emt

# Tokens (los mismos de config.toml). El verde de acción es más oscuro que el de referencia para que
# el texto blanco encima se lea bien (contraste 4,8:1).
VERDE = "#17806c"
TINTA = "#191d38"
NAVY = "#1f3663"
GRIS = "#5b6478"
BORDE = "#e3e8ef"
CELESTE = "#00a0d0"

# Tipos de licitación de Mercado Público (por monto, en UTM).
TIPOS = {"L1": "Licitación < 100 UTM", "E2": "Licitación < 100 UTM", "LE": "Licitación 100–1.000 UTM",
         "CO": "Licitación 100–1.000 UTM", "LP": "Licitación 1.000–2.000 UTM", "B2": "Licitación 1.000–2.000 UTM",
         "LQ": "Licitación 2.000–5.000 UTM", "H2": "Licitación 2.000–5.000 UTM", "LR": "Licitación > 5.000 UTM",
         "I2": "Licitación > 5.000 UTM"}

# Etiqueta de la decisión GO / NO GO: (texto, clase de color).
ETIQUETA_DECISION = {GO: ("GO", "ok"), CONDICIONADO: ("Con condiciones", "atento"),
                     FALTA_PRECIO: ("Falta precio", "neutro"), NO_GO: ("NO GO", "mal")}

CSS = f"""
<style>
/* Barra superior blanca y fija, con sombra suave */
header[data-testid="stHeader"] {{ background: #fff; box-shadow: 0 8px 16px rgba(0,0,0,.08); }}
.block-container {{ max-width: 1320px; }}
h1, h2, h3 {{ color: {NAVY}; letter-spacing: -.01em; }}

/* Encabezado de página: degradado celeste y palabra clave marcada */
.wx-hero {{ padding: 28px 32px; margin: 0 0 18px; border-radius: 20px;
  background: radial-gradient(100% 120% at 75% 0%, rgba(0,160,208,.30) 0%, rgba(0,160,208,.10) 35%, #fff 75%);
  border: 1px solid {BORDE}; }}
.wx-hero .wx-eyebrow {{ font: 600 13px Montserrat, sans-serif; text-transform: uppercase; letter-spacing: .08em;
  color: #0b6f8c; margin-bottom: 6px; }}
h1 {{ font-size: 2.2rem !important; }}
.wx-hero h1 {{ font: 800 34px/1.15 Montserrat, sans-serif; color: {TINTA}; margin: 0; padding: 0; }}
.wx-hero h1 mark {{ background: #ddecf3; color: inherit; padding: 0 .2em; border-radius: 6px; }}
.wx-hero p {{ color: {GRIS}; margin: 8px 0 0; font-size: 15px; }}

/* Indicadores: caja celeste con columnas separadas por líneas */
.wx-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); background: #f2f9fa;
  border-radius: 15px; padding: 18px 8px; margin: 4px 0 22px; }}
.wx-kpi {{ text-align: center; padding: 4px 12px; border-left: 1px solid #cfe6ec; }}
.wx-kpi:first-child {{ border-left: none; }}
.wx-kpi b {{ display: block; font: 700 38px/1.15 Montserrat, sans-serif; color: {NAVY}; }}
.wx-kpi span {{ color: {GRIS}; font-size: 14px; }}
@media (max-width: 640px) {{ .wx-kpi {{ border-left: none; border-top: 1px solid #cfe6ec; padding: 10px; }}
  .wx-kpi:first-child {{ border-top: none; }} .wx-kpi b {{ font-size: 30px; }} .wx-hero h1 {{ font-size: 26px; }} }}

/* Tarjetas (contenedores con clave wxcard_…): blancas, borde fino, sombra al pasar el mouse */
div[class*="st-key-wxcard"] {{ background: #fff; border: 1px solid {BORDE}; border-radius: 20px;
  padding: 16px 18px 12px; transition: box-shadow .15s, transform .15s; height: 100%; }}
div[class*="st-key-wxcard"]:hover {{ box-shadow: 0 14px 34px rgba(31,54,99,.10); transform: translateY(-1px); }}
.wx-card-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; min-height: 26px; }}
.wx-card-title {{ font: 700 17px/1.35 Montserrat, sans-serif; color: {TINTA}; margin: 0 0 6px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 46px; }}
.wx-card-sub {{ color: {GRIS}; font-size: 13.5px; margin-bottom: 12px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }}
.wx-card-datos {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; border-top: 1px solid {BORDE};
  padding-top: 10px; }}
.wx-card-datos small {{ display: block; color: {GRIS}; font-size: 12px; }}
.wx-card-datos b {{ font: 700 15px Montserrat, sans-serif; color: {TINTA}; }}
.wx-card-pie {{ color: {GRIS}; font-size: 12px; margin-top: 8px; }}

/* Etiquetas en píldora */
.wx-tag {{ display: inline-flex; align-items: center; height: 24px; padding: 0 10px; border-radius: 999px;
  font: 600 12px Montserrat, sans-serif; background: #edf0f4; color: #45556c; white-space: nowrap; }}
.wx-tag.ok {{ background: #e0ffe3; color: #207728; }}
.wx-tag.atento {{ background: #fff3d1; color: #7a5200; }}
.wx-tag.mal {{ background: #f8d7da; color: #842029; }}
.wx-tag.info {{ background: #d9f1f8; color: #0b5c73; }}
.wx-tag.nueva {{ background: #e8e2f3; color: #4f3f6b; }}
.wx-tag.urgente {{ background: #ffe1d6; color: #9a3412; }}
.wx-tag.navy {{ background: {NAVY}; color: #fff; }}

/* Botones: el primario es el único color de acción */
.stButton button, .stLinkButton a, .stDownloadButton button {{ font-weight: 600; }}
</style>
"""


def aplicar() -> None:
    """Carga el CSS. Va una vez por corrida, al comienzo de app.py."""
    st.html(CSS)


def etiqueta(texto: str, tono: str = "") -> str:
    return f'<span class="wx-tag {tono}">{escape(str(texto))}</span>'


def encabezado(titulo: str, marcada: str = "", subtitulo: str = "", antetitulo: str = "") -> None:
    """Encabezado de página con degradado. `marcada` se resalta (debe ser parte de `titulo`)."""
    t = escape(titulo)
    if marcada and marcada in titulo:
        t = t.replace(escape(marcada), f"<mark>{escape(marcada)}</mark>", 1)
    st.html('<div class="wx-hero">' + (f'<div class="wx-eyebrow">{escape(antetitulo)}</div>' if antetitulo else "")
            + f"<h1>{t}</h1>" + (f"<p>{escape(subtitulo)}</p>" if subtitulo else "") + "</div>")


def indicadores(valores: list[tuple[str, str]]) -> None:
    """Caja de números grandes: [(valor, descripción), …]."""
    st.html('<div class="wx-kpis">' + "".join(
        f'<div class="wx-kpi"><b>{escape(str(v))}</b><span>{escape(d)}</span></div>' for v, d in valores) + "</div>")


def _monto_corto(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    if valor >= 1_000_000:
        return f"${valor / 1_000_000:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")
    return comun.clp(valor)


def tarjeta(lic: dict, prep: dict, decision=None, clave: str = "", boton: str = "Ver detalle",
            bloqueada: bool = False, datos: list[tuple[str, str]] | None = None) -> bool:
    """Tarjeta de una licitación o Compra Ágil. Devuelve True si se tocó su botón. `datos` reemplaza
    los tres datos de abajo (monto, cierre y entrega o región)."""
    codigo = lic["codigo"]
    hoy = pd.Timestamp.now(tz="America/Santiago").date()
    agil = es_compra_agil(lic)
    tags = []
    if agil:
        llamado = lic.get("llamado")
        tags.append(etiqueta("Compra Ágil" + (f" · {llamado}º llamado" if llamado else ""), "info"))
    else:
        tags.append(etiqueta(TIPOS.get(lic.get("tipo"), "Licitación"), "navy"))
    if decision is not None:
        tags.append(etiqueta(*ETIQUETA_DECISION.get(decision, ("Falta precio", "neutro"))))
    if es_nueva(lic, hoy):
        tags.append(etiqueta("Nueva", "nueva"))
    dias = lic.get("dias_restantes")
    if dias is not None and dias <= 2:
        tags.append(etiqueta("Cierra " + comun.dias_texto(dias), "urgente"))
    if bloqueada:
        tags.append(etiqueta("Solo EMT", "mal"))
    if codigo in prep["mercado"]:
        tags.append(etiqueta("Con precios", "ok"))
    monto, origen = monto_referencial(lic, prep["items"].get(codigo), comun.supuestos().get("utm"))
    # Monto no publicado: «≈» estimado con OC, «≤» tope del tipo, «≥» piso (ver AYUDA_MONTO).
    monto_txt = ("" if not origen or origen == "Publicado" else origen[0] + " ") + _monto_corto(monto)
    tercero = (("Entrega", f"{lic['plazo_entrega_dias']:g} día" + ("" if lic["plazo_entrega_dias"] == 1 else "s")) if agil and lic.get("plazo_entrega_dias") is not None
               else ("Región", comun.region_corta(lic.get("region")) or "—"))
    datos = datos or [("Monto", monto_txt), ("Cierre", comun.fecha_hora(lic.get("fecha_cierre"), corta=True)), tercero]
    sub = " · ".join(x for x in (lic.get("organismo"), None if tercero[0] == "Región" else
                                 comun.region_corta(lic.get("region"))) if x)
    with st.container(key=f"wxcard_{clave}_{codigo}"):
        st.html(f'<div class="wx-card-tags">{"".join(tags)}</div>'
                f'<div class="wx-card-title" title="{escape(lic.get("nombre") or "")}">{escape(lic.get("nombre") or "")}</div>'
                f'<div class="wx-card-sub">{escape(sub) or "&nbsp;"}</div>'
                '<div class="wx-card-datos">' + "".join(
                    f"<div><small>{escape(t)}</small><b>{escape(v)}</b></div>" for t, v in datos) + "</div>"
                f'<div class="wx-card-pie">{escape(codigo)} · {escape(lic.get("rubro_nombre") or "")}</div>')
        return st.button(boton, key=f"ver_{clave}_{codigo}", width="stretch")


def grilla(lics: list[dict], prep: dict, decisiones: dict, clave: str, columnas: int = 3,
           boton: str = "Ver detalle", bloquear_emt: bool = False, datos: dict | None = None) -> dict | None:
    """Tarjetas en columnas. Devuelve la licitación cuyo botón se tocó (o None). `datos`: por código,
    los datos de abajo de su tarjeta (si no, monto, cierre y entrega o región)."""
    elegida = None
    for inicio in range(0, len(lics), columnas):
        cols = st.columns(columnas, gap="medium")
        for col, lic in zip(cols, lics[inicio:inicio + columnas]):
            with col:
                if tarjeta(lic, prep, decisiones.get(lic["codigo"]), clave, boton,
                           bloqueada=bloquear_emt and solo_emt(lic), datos=(datos or {}).get(lic["codigo"])):
                    elegida = lic
    return elegida


def monto_corto(valor) -> str:
    return _monto_corto(valor)
