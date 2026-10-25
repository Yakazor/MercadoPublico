import json
from datetime import date

import pytest

from radar.orden_proveedor import LINEAS_MINIMAS, crear_orden, precio_neto, siguiente_numero, validar


def _datos(**cambios):
    datos = {
        "numero": "OC-2026-001",
        "fecha": "2026-10-21",
        "comprador": {"tipo": "persona_natural", "nombre": "Ana Pérez", "rut": "11.111.111-1",
                      "giro": "Comercio", "domicilio": "Calle 1", "contacto": "+56 9"},
        "proveedor": {"razon_social": "Proveedor SpA", "rut": "76.000.000-0"},
        "items": [{"descripcion": "Silla plegable", "cantidad": 40, "precio_unitario_neto": 12597},
                  {"descripcion": "Toldo 3x3", "cantidad": 30, "precio_con_iva": 32990}],
    }
    datos.update(cambios)
    return datos


def _celdas(ws):
    return {c.value for fila in ws.iter_rows() for c in fila if c.value is not None}


def test_precio_neto_quita_iva_y_redondea_al_peso():
    assert precio_neto({"precio_con_iva": 32990}) == 27723
    assert precio_neto({"precio_unitario_neto": 100, "precio_con_iva": 999}) == 100
    assert precio_neto({}) is None


def test_validar_orden_completa_y_lo_que_falta():
    assert validar(_datos()) == []
    faltan = validar(_datos(proveedor={}, items=[{"descripcion": "x"}]))
    assert "proveedor.razon_social" in faltan
    assert "items[1].cantidad" in faltan and "items[1].precio" in faltan
    assert "comprador.tipo: «otro» no es persona_natural ni empresa" in validar(_datos(comprador={"tipo": "otro"}))


def test_persona_natural_pide_nombre_y_giro_no_razon_social():
    ws = crear_orden(_datos())["Orden de Compra"]
    celdas = _celdas(ws)
    assert {"COMPRADOR (persona natural con giro)", "Nombre completo", "Giro", "Ana Pérez"} <= celdas
    assert "Firma comprador (nombre y RUT)" in celdas
    assert "COMPRADOR (empresa)" not in celdas


def test_empresa_pide_razon_social():
    datos = _datos(comprador={"tipo": "empresa", "razon_social": "Mi SpA", "rut": "1-9"})
    celdas = _celdas(crear_orden(datos)["Orden de Compra"])
    assert {"COMPRADOR (empresa)", "Mi SpA", "Firma y timbre comprador"} <= celdas


def test_items_fechas_y_formulas():
    ws = crear_orden(_datos())["Orden de Compra"]
    filas = {ws.cell(r, 3).value: r for r in range(1, ws.max_row + 1)}
    r = filas["Silla plegable"]
    assert ws[f"E{r}"].value == 40 and ws[f"F{r}"].value == 12597
    assert ws[f"G{r}"].value == f'=IF(OR(E{r}="",F{r}=""),"",E{r}*F{r})'
    assert ws[f"F{filas['Toldo 3x3']}"].value == 27723
    assert ws["F3"].value == date(2026, 10, 21)
    assert ws["F3"].number_format == "dd-mm-yyyy"
    formulas = {c.value for fila in ws.iter_rows() for c in fila if str(c.value).startswith("=SUM")}
    assert len(formulas) == 1


def test_mas_items_que_lineas_minimas_agrega_filas():
    items = [{"descripcion": f"Producto {i}", "cantidad": 1, "precio_unitario_neto": 10}
             for i in range(LINEAS_MINIMAS + 5)]
    ws = crear_orden(_datos(items=items))["Orden de Compra"]
    numeros = [ws.cell(r, 1).value for r in range(1, ws.max_row + 1) if isinstance(ws.cell(r, 1).value, int)]
    assert numeros == list(range(1, LINEAS_MINIMAS + 6))


def test_plantilla_en_blanco_y_tipo_invalido():
    ws = crear_orden()["Orden de Compra"]
    assert "COMPRADOR (persona natural con giro)" in _celdas(ws)
    with pytest.raises(ValueError):
        crear_orden({"comprador": {"tipo": "otro"}})


def test_siguiente_numero_ignora_ejemplo_y_otros_anios(tmp_path):
    assert siguiente_numero(tmp_path, 2026) == "OC-2026-001"
    for nombre, numero in [("ejemplo.json", "OC-2026-050"), ("a.json", "OC-2026-003"), ("b.json", "OC-2025-009")]:
        (tmp_path / nombre).write_text(json.dumps({"numero": numero}), encoding="utf-8")
    (tmp_path / "roto.json").write_text("{", encoding="utf-8")
    assert siguiente_numero(tmp_path, 2026) == "OC-2026-004"


def test_script_usa_las_carpetas_de_proveedores():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import orden_proveedor as script

    assert script.CARPETA.parent == script.PLANTILLAS.parent == script.PROVEEDORES
    assert script.PROVEEDORES.name == "proveedores"
    for tipo in script.NOMBRE_PLANTILLA.values():
        assert (script.PLANTILLAS / f"Plantilla_Orden_de_Compra_{tipo}.xlsx").exists()
    ejemplo = json.loads((script.CARPETA / "ejemplo.json").read_text(encoding="utf-8"))
    assert validar(ejemplo) == []


def test_descripcion_con_caracteres_de_control():
    items = [{"descripcion": "Calzas sigla 10U\x02POCA", "cantidad": 1, "precio_unitario_neto": 10}]
    assert "Calzas sigla 10UPOCA" in _celdas(crear_orden(_datos(items=items))["Orden de Compra"])
