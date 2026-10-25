import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from radar.evaluacion import NO_GO
from radar.orden_proveedor import totales
from radar.plataforma import (CHILE, COTIZACION, ESTIMADA_OC, datos_orden, evaluar_licitacion, filtrar, leer_datos,
                              opciones, orden_xlsx, preparar, ranking, supuestos_config)

AHORA = datetime(2026, 10, 24, 12, 0, tzinfo=CHILE)
RAIZ = Path(__file__).resolve().parents[1]


def _lic(codigo, **cambios):
    lic = {"codigo": codigo, "nombre": "Sillas de oficina", "organismo": "Municipalidad", "tipo": "LE",
           "region": "Región Metropolitana de Santiago", "monto_estimado": 2_000_000, "moneda": "CLP",
           "fecha_cierre": "2026-10-30 15:00:00", "dias_restantes": 7, "rubro_nombre": "Mobiliario",
           "url": f"https://x/{codigo}"}
    return lic | cambios


def _datos():
    return {
        "licitaciones": [
            _lic("1-1-LE26"),
            _lic("2-2-COT26", nombre="Mochilas escolares", tipo="Compra Ágil", monto_estimado=674_000,
                 fecha_cierre="2026-10-26 10:00:00", plazo_entrega_dias=3.0, llamado=1,
                 direccion_entrega="Av. San Gregorio 494"),
            _lic("3-3-LE26", nombre="Ya cerró", fecha_cierre="2026-10-24 09:00:00"),
            _lic("4-4-LE26", nombre="Útiles de aseo", monto_estimado=None, rubro_nombre="Aseo",
                 region="Región de Valparaíso", fecha_cierre="2026-10-25 12:00:00"),
        ],
        "items": [
            {"codigo": "1-1-LE26", "linea": 1, "producto": "Silla", "descripcion": "Silla ergonómica",
             "cantidad": 10, "unidad": "Unidad", "ref_mediana": 60_000},
            {"codigo": "1-1-LE26", "linea": 2, "producto": "Escritorio", "cantidad": 2, "unidad": "Unidad",
             "ref_mediana": 120_000},
            {"codigo": "2-2-COT26", "linea": 1, "producto": "Mochilas", "descripcion": "MOCHILA ESCOLAR 30 L",
             "cantidad": 15, "unidad": "EA", "ref_mediana": 14_072},
        ],
        "mercado": [
            {"codigo": "1-1-LE26", "linea": 1, "tienda": "Tienda A", "producto_mercado": "Silla Pro",
             "precio_unitario_neto": 40_000, "coincidencia": "exacta", "verificado": True},
            {"codigo": "1-1-LE26", "linea": 1, "tienda": "Tienda B", "precio_unitario_neto": 10,
             "coincidencia": "exacta", "descartado": True},
        ],
        "meta": [{"generado": "2026-10-23T12:44:58-03:00"}],
    }


def test_preparar_deja_las_abiertas_con_dias_recalculados():
    prep = preparar(_datos(), AHORA)
    assert [l["codigo"] for l in prep["licitaciones"]] == ["1-1-LE26", "2-2-COT26", "4-4-LE26"]
    assert {l["codigo"]: l["dias_restantes"] for l in prep["licitaciones"]} == \
        {"1-1-LE26": 6, "2-2-COT26": 2, "4-4-LE26": 1}
    assert len(prep["items"]["1-1-LE26"]) == 2
    assert [op["tienda"] for op in prep["mercado"]["1-1-LE26"]] == ["Tienda A"]     # sin la descartada
    assert prep["meta"]["generado"].startswith("2026-10-23")


def test_filtrar_por_texto_tipo_monto_plazo_y_precios():
    lics = preparar(_datos(), AHORA)["licitaciones"]
    codigos = lambda **k: [l["codigo"] for l in filtrar(lics, **k)]  # noqa: E731
    assert codigos() == ["4-4-LE26", "2-2-COT26", "1-1-LE26"]                       # por fecha de cierre
    assert codigos(texto="utiles ASEO") == ["4-4-LE26"]                             # sin tildes ni mayúsculas
    assert codigos(compra_agil=True) == ["2-2-COT26"]
    assert codigos(monto_min=1_000_000) == ["4-4-LE26", "1-1-LE26"]                 # sin monto: no se descarta
    assert codigos(max_dias=2, compra_agil=False) == ["4-4-LE26"]
    assert codigos(con_precios={"1-1-LE26"}) == ["1-1-LE26"]
    assert codigos(plazo_max=2, compra_agil=True) == []
    assert codigos(llamado=1) == ["2-2-COT26"]
    assert codigos(regiones=["Región de Valparaíso"], rubros=["Aseo"]) == ["4-4-LE26"]


def test_cotizacion_manda_sobre_la_tienda_y_estimacion_con_oc():
    prep = preparar(_datos(), AHORA)
    items, mercado = prep["items"]["1-1-LE26"], prep["mercado"]["1-1-LE26"]
    ops = opciones(items, mercado, {1: 30_000})
    assert [(o["linea"], o["tienda"]) for o in ops] == [(1, COTIZACION)]
    ops = opciones(items, mercado, estimar_oc=True)
    estimada = next(o for o in ops if o["linea"] == 2)
    assert estimada["coincidencia"] == ESTIMADA_OC and not estimada["verificado"]
    p, _ = evaluar_licitacion(prep["licitaciones"][0], items, ops)
    assert p["items"][1]["oferta_unitaria_neta"] == pytest.approx(120_000)          # oferta = mediana del Estado


def test_evaluar_compra_agil_con_cotizacion():
    prep = preparar(_datos(), AHORA)
    lic = next(l for l in prep["licitaciones"] if l["codigo"] == "2-2-COT26")
    items = prep["items"]["2-2-COT26"]
    p, ev = evaluar_licitacion(lic, items, opciones(items, [], {1: 25_000}))
    assert p["oferta_total"] == pytest.approx(25_000 * 15 * 1.05 * 1.2 * 1.19)
    assert ev.cobertura == 1 and ev.decision != NO_GO
    p, ev = evaluar_licitacion(lic, items, opciones(items, []))
    assert p["items_sin_precio"] == 1 and ev.decision == NO_GO


def test_ranking_con_precios_cotizaciones_o_estimacion():
    prep = preparar(_datos(), AHORA)
    assert [l["codigo"] for l, _, _ in ranking(prep)] == ["1-1-LE26"]
    con_cotizacion = ranking(prep, cotizaciones={"2-2-COT26": {1: 20_000}})
    assert {l["codigo"] for l, _, _ in con_cotizacion} == {"1-1-LE26", "2-2-COT26"}
    assert len(ranking(prep, estimar_oc=True)) == 2                                 # 4-4 no tiene ítems


def test_supuestos_de_config_y_orden_desde_el_presupuesto():
    s = supuestos_config({"evaluacion": {"valor_hora": 9000, "otro": 1}})
    assert s["valor_hora"] == 9000 and "otro" not in s
    prep = preparar(_datos(), AHORA)
    lic = next(l for l in prep["licitaciones"] if l["codigo"] == "2-2-COT26")
    items = prep["items"]["2-2-COT26"]
    p, _ = evaluar_licitacion(lic, items, opciones(items, [], {1: 21_008.4}))
    datos = datos_orden(lic, p)
    assert datos["items"] == [{"descripcion": "MOCHILA ESCOLAR 30 L", "unidad": "EA", "cantidad": 15,
                               "precio_unitario_neto": 21_008}]
    assert datos["referencia"]["licitacion"] == "2-2-COT26"
    assert "Av. San Gregorio 494" in datos["condiciones"]["lugar_entrega"]
    lic1 = prep["licitaciones"][0]
    items1 = prep["items"]["1-1-LE26"]
    p1, _ = evaluar_licitacion(lic1, items1, opciones(items1, prep["mercado"]["1-1-LE26"]))
    assert [i["descripcion"] for i in datos_orden(lic1, p1, "Tienda A")["items"]] == ["Silla Pro"]
    wb = load_workbook(io.BytesIO(orden_xlsx(datos | {"numero": "OC-2026-009"})))
    celdas = {c.value for fila in wb["Orden de Compra"].iter_rows() for c in fila}
    assert {"OC-2026-009", "MOCHILA ESCOLAR 30 L", 21_008} <= celdas
    assert totales(datos | {"descuento": 8})["total"] == 15 * 21_008 - 8 + round((15 * 21_008 - 8) * 0.19)


def test_leer_datos_desde_carpeta(tmp_path):
    for nombre, valor in _datos().items():
        (tmp_path / f"{nombre}.json").write_text(json.dumps(valor), encoding="utf-8")
    assert leer_datos(str(tmp_path))["licitaciones"][0]["codigo"] == "1-1-LE26"


def _pagina(modulo: str, funcion: str, raiz: str) -> None:
    """Corre una página de la plataforma dentro de AppTest."""
    import importlib
    import sys

    sys.path.insert(0, raiz + "/plataforma")
    getattr(importlib.import_module(modulo), funcion)()


@pytest.mark.parametrize("modulo, funcion", [("inicio", "pagina"), ("explorar", "licitaciones"),
                                             ("explorar", "compras_agiles"), ("evaluar", "pagina"),
                                             ("orden", "pagina"), ("manuales", "pagina"), ("actualizar", "pagina")])
def test_paginas_cargan_sin_errores(tmp_path, monkeypatch, modulo, funcion):
    pytest.importorskip("streamlit")
    import requests
    from streamlit.testing.v1 import AppTest

    # «Actualizar datos» consulta GitHub: sin red en las pruebas.
    monkeypatch.setattr(requests, "get", lambda url, **k: _Respuesta(200, {"workflow_runs": [
        _run(1, "radar-diario.yml", "completed", "success")]}))

    datos = _datos()
    for lic in datos["licitaciones"]:       # que sigan abiertas el día que corra el test
        lic["fecha_cierre"] = "2099-01-01 12:00:00"
    for nombre, valor in datos.items():
        (tmp_path / f"{nombre}.json").write_text(json.dumps(valor), encoding="utf-8")
    monkeypatch.setenv("RADAR_DATOS", str(tmp_path))
    at = AppTest.from_function(_pagina, args=(modulo, funcion, str(RAIZ)), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title


def test_app_completa_abre_en_inicio(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    for nombre, valor in _datos().items():
        (tmp_path / f"{nombre}.json").write_text(json.dumps(valor), encoding="utf-8")
    monkeypatch.setenv("RADAR_DATOS", str(tmp_path))
    at = AppTest.from_file(str(RAIZ / "plataforma" / "app.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Radar Mercado Público"


class _Respuesta:
    def __init__(self, status, datos=None, cabeceras=None):
        self.status_code, self._datos, self.headers, self.text = status, datos or {}, cabeceras or {}, ""

    def json(self):
        return self._datos

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _run(id_, archivo, status, conclusion=None, creada="2026-10-25T00:10:00Z", fin="2026-10-25T00:13:00Z"):
    return {"id": id_, "path": f".github/workflows/{archivo}", "name": archivo, "status": status,
            "conclusion": conclusion, "event": "workflow_dispatch", "run_started_at": creada,
            "created_at": creada, "updated_at": fin, "html_url": f"https://github.com/x/{id_}"}


def test_corridas_traduce_estados_y_errores(monkeypatch):
    from radar import actualizacion as a

    pedidos = []
    runs = [_run(1, "radar-diario.yml", "completed", "success"), _run(2, "compra-agil.yml", "queued"),
            _run(3, "ordenes-historicas.yml", "in_progress")]
    monkeypatch.setattr(a.requests, "get", lambda url, **k: pedidos.append((url, k)) or
                        _Respuesta(200, {"workflow_runs": runs}))
    lista = a.corridas("tok")
    assert [(c["workflow"], c["estado"], c["resultado"]) for c in lista] == [
        ("radar-diario.yml", "completed", "success"), ("compra-agil.yml", "en_cola", None),
        ("ordenes-historicas.yml", "in_progress", None)]
    assert lista[0]["nombre"] == "Licitaciones (radar diario)" and lista[0]["fin"].minute == 13
    assert lista[1]["fin"] is None
    assert pedidos[0][1]["params"]["branch"] == "feature/api-mercadopublico"
    assert pedidos[0][1]["headers"]["Authorization"] == "Bearer tok"
    monkeypatch.setattr(a.requests, "get", lambda url, **k: _Respuesta(401))
    with pytest.raises(a.ErrorGitHub, match="token"):
        a.corridas("malo")
    monkeypatch.setattr(a.requests, "get", lambda url, **k: _Respuesta(403, cabeceras={"x-ratelimit-remaining": "0"}))
    with pytest.raises(a.ErrorGitHub, match="limitó"):
        a.corridas()


def test_actualizar_no_pisa_corridas_en_cola(monkeypatch):
    from radar import actualizacion as a

    lanzados = []
    monkeypatch.setattr(a.requests, "post", lambda url, **k: lanzados.append((url.split("/")[-2], k["json"])) or
                        _Respuesta(204))
    libre = [{"workflow": "radar-diario.yml", "estado": "completed"}]
    assert a.actualizar("tok", libre) == [("compra-agil.yml", "lanzado"), ("radar-diario.yml", "lanzado")]
    assert lanzados == [("compra-agil.yml", {"ref": "feature/api-mercadopublico", "inputs": {}}),
                        ("radar-diario.yml", {"ref": "feature/api-mercadopublico", "inputs": {}})]
    lanzados.clear()
    ocupado = [{"workflow": "compra-agil.yml", "estado": "in_progress"},
               {"workflow": "ordenes-historicas.yml", "estado": "en_cola"}]
    resultado = dict(a.actualizar("tok", ocupado))
    assert resultado["compra-agil.yml"] == "ya está corriendo o en cola"
    assert "misma base" in resultado["radar-diario.yml"] and lanzados == []
    with pytest.raises(a.ErrorGitHub):
        a.lanzar("radar-diario.yml", "")
    with pytest.raises(ValueError):
        a.lanzar("otro.yml", "tok")
    monkeypatch.setattr(a.requests, "post", lambda url, **k: _Respuesta(404))
    with pytest.raises(a.ErrorGitHub, match="Read and write"):
        a.lanzar("radar-diario.yml", "tok")


def test_leer_datos_con_marca_salta_la_cache(monkeypatch):
    import radar.plataforma as plataforma

    urls = []
    monkeypatch.setattr(plataforma.requests, "get", lambda url, params=None, **k: urls.append((url, params)) or
                        _Respuesta(200, []))
    plataforma.leer_datos("https://x/datos/", marca="20261025")
    assert urls[0] == ("https://x/datos/licitaciones.json", {"v": "20261025"}) and len(urls) == 4
