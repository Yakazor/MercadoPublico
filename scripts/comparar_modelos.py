"""Compara modelos de Claude en la búsqueda de proveedores: mismas licitaciones, cada modelo.

Uso (lo corre el workflow «Comparar modelos de búsqueda», con el secreto ANTHROPIC_API_KEY):
    python scripts/comparar_modelos.py --datos <carpeta con licitaciones.json e items.json> \\
        --codigos 1057448-53-LE26 1362-13-LE26 --modelos claude-opus-5-5 claude-sonnet-5-5 \\
        --salida comparacion

Por cada modelo y licitación guarda el resultado en <salida>/<modelo>_<código>.json (no lo sube a
la rama `proveedores`) y escribe en <salida>/resumen.md: proveedores, precios, líneas con precio,
verificados, exactos o equivalentes, costo y tiempo. Cuesta unos US$0,10–0,80 por búsqueda.
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import _ruta  # noqa: F401
from radar import proveedores as prov


def _lista(ruta: Path) -> list:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return datos if isinstance(datos, list) else datos.get("licitaciones", [])


def una(modelo: str, lic: dict, items: list[dict], clave: str, salida: Path) -> dict:
    cfg = prov.configuracion() | {"modelo": modelo}
    inicio = time.time()
    try:
        r = prov.buscar(lic, items, clave, cfg)
    except Exception as e:  # noqa: BLE001 — se informa en el resumen y se sigue con las demás
        r = {"error": f"{type(e).__name__}: {e}"[:1500]}
    r |= {"segundos": round(time.time() - inicio), "lineas_pedidas": len(items), "modelo_pedido": modelo}
    (salida / f"{modelo}_{lic['codigo']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def fila(codigo: str, r: dict) -> str:
    if r.get("error"):
        return f"| {codigo} | {r['modelo_pedido']} | error: {r['error'][:120]} | | | | | | {r['segundos']} | |"
    precios = r.get("precios") or []
    lineas = {m["linea"] for m in precios}
    buenas = {m["linea"] for m in precios if m.get("coincidencia") in ("exacta", "equivalente")}
    verif = sum(1 for m in precios if m.get("verificado"))
    costo_lineas = sum(min(m["precio_unitario_neto"] for m in precios if m["linea"] == l) for l in lineas)
    return (f"| {codigo} | {r['modelo_pedido']} | {len(r.get('proveedores') or [])} "
            f"({sum(1 for p in r.get('proveedores') or [] if p.get('correo'))} con correo) | {len(precios)} | "
            f"{len(lineas)}/{r['lineas_pedidas']} | {len(buenas)} | {verif} | US$ {r.get('costo_usd', 0):.2f} | "
            f"{r['segundos']} | {costo_lineas:,.0f} |".replace(",", "."))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", required=True)
    ap.add_argument("--codigos", nargs="+", required=True)
    ap.add_argument("--modelos", nargs="+", default=["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
    ap.add_argument("--salida", default="comparacion")
    a = ap.parse_args()
    clave = os.environ.get("ANTHROPIC_API_KEY")
    if not clave:
        raise SystemExit("Falta ANTHROPIC_API_KEY (secreto del repositorio).")
    datos, salida = Path(a.datos), Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    lics = {l["codigo"]: l for l in _lista(datos / "licitaciones.json")}
    items = json.loads((datos / "items.json").read_text(encoding="utf-8"))
    trabajos = []
    for codigo in a.codigos:
        if codigo not in lics:
            print(f"{codigo}: no está entre las licitaciones abiertas; se omite.")
            continue
        suyos = [it for it in items if it.get("codigo") == codigo]
        trabajos += [(m, codigo, suyos) for m in a.modelos]
    # Un hilo por modelo: cada modelo recorre las licitaciones en orden (no satura la API).
    with ThreadPoolExecutor(max_workers=len(a.modelos)) as ex:
        resultados = list(ex.map(lambda t: (t[1], una(t[0], lics[t[1]], t[2], clave, salida)), trabajos))
    lineas = ["# Comparación de modelos en la búsqueda de proveedores", "",
              "| Licitación | Modelo | Proveedores | Precios | Líneas con precio | Exactas o equivalentes | "
              "Verificados | Costo | Segundos | Costo neto unitario sumado |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    lineas += [fila(codigo, r) for codigo, r in resultados]
    total = {}
    for _, r in resultados:
        total[r["modelo_pedido"]] = total.get(r["modelo_pedido"], 0) + (r.get("costo_usd") or 0)
    lineas += ["", "Costo total por modelo: " + ", ".join(f"{m} US$ {c:.2f}" for m, c in total.items()), ""]
    errores = [f"- {codigo} · {r['modelo_pedido']}: {r['error']}" for codigo, r in resultados if r.get("error")]
    if errores:
        lineas += ["## Errores (mensaje completo)", "", *errores, "",
                   "Una búsqueda con error no informa su costo, pero si alcanzó a buscar sí se cobró.", ""]
    (salida / "resumen.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
