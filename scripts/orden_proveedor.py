"""Llena la orden de compra al proveedor con los datos de un JSON.

Uso:
    python scripts/orden_proveedor.py --datos ordenes_proveedor/OC-2026-001.json [--pdf]
    python scripts/orden_proveedor.py --plantilla persona_natural   # plantilla en blanco
    python scripts/orden_proveedor.py --siguiente                   # próximo número OC-AAAA-NNN

Lee:
    ordenes_proveedor/<numero>.json   datos de la orden (formato: ordenes_proveedor/ejemplo.json)
Escribe:
    ordenes_proveedor/<numero>.xlsx   la orden llena (y .pdf con --pdf, si hay LibreOffice)
    plantillas/Plantilla_Orden_de_Compra_<tipo>.xlsx   con --plantilla

Las órdenes llenas traen RUT y datos personales: `ordenes_proveedor/` no se sube al
repositorio (solo el ejemplo). Con LibreOffice instalado el .xlsx se recalcula para que
los totales se vean también en visores que no calculan fórmulas.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import _ruta  # noqa: F401
from radar.config import RAIZ
from radar.orden_proveedor import crear_orden, siguiente_numero, validar

CARPETA = RAIZ / "ordenes_proveedor"
PLANTILLAS = RAIZ / "plantillas"
NOMBRE_PLANTILLA = {"persona_natural": "Persona_Natural", "empresa": "Empresa"}


def _libreoffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convertir(archivo: Path, formato: str, destino: Path) -> Path | None:
    """Convierte con LibreOffice (calcula las fórmulas); None si no está instalado."""
    soffice = _libreoffice()
    if not soffice:
        return None
    subprocess.run([soffice, "--headless", "--calc", "--convert-to", formato, "--outdir", str(destino),
                    str(archivo)], check=True, capture_output=True, timeout=120)
    salida = destino / f"{archivo.stem}.{formato.split(':')[0]}"
    return salida if salida.exists() else None


def guardar(wb, archivo: Path, pdf: bool = False) -> list[Path]:
    archivo.parent.mkdir(parents=True, exist_ok=True)
    wb.save(archivo)
    escritos = [archivo]
    with tempfile.TemporaryDirectory() as tmp:
        recalculado = _convertir(archivo, "xlsx", Path(tmp))
        if recalculado:
            shutil.move(recalculado, archivo)
        if pdf:
            salida = _convertir(archivo, "pdf", archivo.parent)
            if salida:
                escritos.append(salida)
            else:
                print("Aviso: sin LibreOffice no se puede generar el PDF; expórtalo desde Excel.")
    return escritos


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--datos", type=Path, help="JSON con los datos de la orden")
    g.add_argument("--plantilla", choices=sorted(NOMBRE_PLANTILLA), help="plantilla en blanco")
    g.add_argument("--siguiente", action="store_true", help="muestra el próximo número de OC")
    p.add_argument("--pdf", action="store_true", help="también genera el PDF")
    p.add_argument("--salida", type=Path, help="archivo .xlsx de salida")
    args = p.parse_args()

    if args.siguiente:
        print(siguiente_numero(CARPETA))
        return 0
    if args.plantilla:
        wb = crear_orden({"comprador": {"tipo": args.plantilla}})
        archivo = args.salida or PLANTILLAS / f"Plantilla_Orden_de_Compra_{NOMBRE_PLANTILLA[args.plantilla]}.xlsx"
        for escrito in guardar(wb, archivo, args.pdf):
            print(escrito)
        return 0

    datos = json.loads(args.datos.read_text(encoding="utf-8"))
    if not datos.get("numero"):
        datos["numero"] = siguiente_numero(CARPETA)
    faltan = validar(datos)
    if faltan:
        print("Faltan datos (la orden se genera igual, con esas celdas vacías):")
        for campo in faltan:
            print(f"  - {campo}")
    archivo = args.salida or args.datos.with_name(f"{datos['numero']}.xlsx")
    for escrito in guardar(crear_orden(datos), archivo, args.pdf):
        print(escrito)
    return 0


if __name__ == "__main__":
    sys.exit(main())
