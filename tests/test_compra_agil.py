import json
from datetime import date, datetime

import pytest

from radar import compra_agil
from radar.cliente_api import ErrorApi
from radar.compra_agil import (ClienteCompraAgil, como_licitacion, fecha_chile, listar_publicadas,
                               radar_compra_agil)
from radar.config import cargar_config
from radar.filtro import FiltroRubros
from radar.presupuesto import items_licitacion_presupuesto

FILTRO = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "cloro"]}})


class Resp:
    def __init__(self, status, datos):
        self.status_code, self._datos, self.text = status, datos, json.dumps(datos)
        self.ok = status < 400

    def json(self):
        return self._datos


class Sesion:
    def __init__(self, respuestas):
        self.respuestas, self.llamadas = list(respuestas), []

    def get(self, url, params, headers, timeout):
        self.llamadas.append((url, dict(params), dict(headers)))
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(compra_agil.time, "sleep", lambda s: None)


def _cliente(respuestas):
    c = ClienteCompraAgil("SECRETO", pausa=0, reintentos=2)
    c._sesion = Sesion(respuestas)
    return c


def _ok(payload):
    return Resp(200, {"success": "OK", "trace": None, "payload": payload, "errors": None})


def _error(status, mensaje):
    return Resp(status, {"success": "NOK", "payload": None, "errors": [{"codigo": str(status), "mensaje": mensaje}]})


def _pagina(codigos, pagina, total):
    return _ok({"items": [{"codigo": c, "nombre": f"Compra de guantes {c}",
                           "fechas": {"fecha_cierre": "2026-10-25T15:00:00Z"}} for c in codigos],
                "paginacion": {"numero_pagina": pagina, "total_paginas": total, "total_resultados": 9}})


def _detalle(codigo, nombre="Compra de guantes de nitrilo", productos=None):
    return _ok({
        "codigo": codigo, "nombre": nombre, "descripcion": "Para el CESFAM",
        "estado": {"codigo": "publicada", "glosa": "Publicada"},
        "convocatoria": {"estado_convocatoria": 1},
        "fechas": {"fecha_publicacion": "2026-10-20T10:00:00Z", "fecha_cierre": "2026-10-23T15:00:00Z"},
        "presupuesto": {"monto_disponible_clp": 850000},
        "entrega": {"direccion_entrega": "Av. Siempre Viva 123", "plazo_entrega_dias": 5},
        "institucion": {"organismo_comprador": "Municipalidad X", "unidad_compra": "Salud",
                        "nombre_region": "Metropolitana"},
        "productos_solicitados": productos if productos is not None else [
            {"codigo_producto": 42132203, "nombre": "Guantes de examen de nitrilo",
             "descripcion": "talla M, caja 100", "cantidad": 20, "unidad_medida": "Caja"}],
    })


def test_ticket_va_en_el_encabezado_y_no_en_la_url():
    c = _cliente([_pagina(["A"], 1, 1)])
    listar_publicadas(c, regiones=[13, 5], ahora=datetime(2026, 10, 21))
    url, params, headers = c._sesion.llamadas[0]
    assert url == "https://api2.mercadopublico.cl/v2/compra-agil"
    assert headers == {"ticket": "SECRETO"}
    assert "SECRETO" not in json.dumps(params)
    assert params["estado"] == "publicada" and params["region"] == "13,5"
    assert params["publicado_desde"] == "2026-10-06T00:00:00Z"


def test_recorre_paginas_sin_repetidos():
    c = _cliente([_pagina(["A", "B"], 1, 2), _pagina(["B", "C"], 2, 2)])
    assert [i["codigo"] for i in listar_publicadas(c)] == ["A", "B", "C"]


def test_504_con_pagina_grande_sigue_con_paginas_de_10():
    c = _cliente([_error(504, "Gateway Timeout"), _pagina(["A"], 1, 1)])
    assert [i["codigo"] for i in listar_publicadas(c, tamano_pagina=50)] == ["A"]
    assert [ll[1]["tamano_pagina"] for ll in c._sesion.llamadas] == [50, 10]


def test_ticket_rechazado_es_fatal():
    c = _cliente([_error(403, "El ticket no existe, está inactivo o fue bloqueado.")])
    with pytest.raises(ErrorApi) as e:
        c.listado(estado="publicada")
    assert e.value.fatal and not e.value.temporal


def test_reintenta_errores_del_servidor():
    c = _cliente([_error(500, "error"), _pagina(["A"], 1, 1)])
    assert c.listado()["items"][0]["codigo"] == "A"


def test_fecha_chile_quita_la_z():
    assert fecha_chile("2026-10-23T15:00:00Z") == "2026-10-23T15:00:00"
    assert fecha_chile(None) is None


def test_fecha_cierre_real_sin_t_ni_segundos():
    # Formato real de fechas.fecha_cierre: "2026-10-23 15:00" (hora de Chile).
    assert fecha_chile("2026-10-23 15:00") == "2026-10-23T15:00:00"
    payload = _detalle("X").json()["payload"]
    payload["fechas"]["fecha_cierre"] = "2026-10-23 15:00"
    c = _cliente([_pagina(["X"], 1, 1), _ok(payload)])
    r = radar_compra_agil(c, FILTRO, hoy=date(2026, 10, 21))
    assert r.filas[0]["fecha_cierre"] == "2026-10-23 15:00:00" and r.filas[0]["dias_restantes"] == 2


def test_monto_en_utm_no_se_toma_como_pesos_y_region_de_respaldo():
    payload = _detalle("U").json()["payload"]
    payload["presupuesto"] = {"moneda": "UTM", "monto_disponible": 50}
    payload["institucion"] = {"organismo_comprador": "X", "region": 8, "nombre_region": None}
    det = como_licitacion(payload)
    assert det["MontoEstimado"] is None and det["Comprador"]["RegionUnidad"] == "Región 8"


def test_como_licitacion_y_presupuesto():
    det = como_licitacion(_detalle("1-2-COT26").json()["payload"])
    assert det["Tipo"] == "Compra Ágil" and det["MontoEstimado"] == 850000 and det["Llamado"] == 1
    assert det["Fechas"]["FechaCierre"] == "2026-10-23T15:00:00"
    items = items_licitacion_presupuesto("1-2-COT26", "aseo", det)
    assert items[0]["producto"] == "Guantes de examen de nitrilo"
    assert items[0]["cantidad"] == 20 and items[0]["unidad"] == "Caja" and items[0]["linea"] == 1


def test_radar_clasifica_y_descarta():
    pagina = _pagina(["A", "B"], 1, 1)
    pagina._datos["payload"]["items"][1]["nombre"] = "Servicio de banquetería"
    c = _cliente([pagina, _detalle("A")])
    r = radar_compra_agil(c, FILTRO, hoy=date(2026, 10, 21))
    assert r.publicadas == 2 and r.candidatas == 1      # B no pasa el filtro por nombre: sin detalle
    assert [f["codigo"] for f in r.filas] == ["A"]
    fila = r.filas[0]
    assert fila["tipo"] == "Compra Ágil" and fila["llamado"] == 1
    assert fila["url"] == "https://buscador.mercadopublico.cl/ficha?code=A"
    assert fila["dias_restantes"] == 2 and fila["rubro"] == "aseo"
    assert set(r.detalles) == {"A"}


def test_429_espera_una_vez_y_reintenta(monkeypatch):
    esperas = []
    monkeypatch.setattr(compra_agil.time, "sleep", esperas.append)
    c = _cliente([_error(429, "límite"), _pagina(["A"], 1, 1)])
    c.max_espera_429 = 600
    assert c.listado()["items"][0]["codigo"] == "A"
    assert 600 in esperas


def test_429_repetido_guarda_lo_obtenido():
    c = _cliente([_pagina(["A", "B"], 1, 1), _detalle("A"), _error(429, "Se ha alcanzado el límite"),
                  _error(429, "Se ha alcanzado el límite")])
    r = radar_compra_agil(c, FILTRO, hoy=date(2026, 10, 21))
    assert [f["codigo"] for f in r.filas] == ["A"]
    assert r.fallidas == {"B"} and "429" in r.detenida


def test_config_real_detecta_aseo():
    filtro = FiltroRubros.desde_config(cargar_config())
    c = _cliente([_pagina(["A"], 1, 1), _detalle("A", nombre="Adquisición de artículos de aseo", productos=[
        {"nombre": "Cloro", "descripcion": "cloro tradicional 5 litros", "cantidad": 10, "unidad_medida": "Unidad"},
        {"nombre": "Papel higiénico", "descripcion": "rollo 500 m", "cantidad": 24, "unidad_medida": "Unidad"}])])
    r = radar_compra_agil(c, filtro, hoy=date(2026, 10, 21))
    assert len(r.filas) == 1 and r.filas[0]["rubro"] == "insumos_medicos_aseo"
