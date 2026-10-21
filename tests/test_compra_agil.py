import json
from datetime import date, datetime

import pytest

from radar import compra_agil
from radar.cliente_api import ErrorApi
from radar.compra_agil import (ClienteCompraAgil, actualizar_compras_agiles, como_licitacion, estado_vacio,
                               fecha_chile, listar_publicadas)
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
        """El listado se recorre por día: los días sin una página en la cola reciben
        una página vacía (la cola sigue con los detalles)."""
        self.llamadas.append((url, dict(params), dict(headers)))
        siguiente = self.respuestas[0] if self.respuestas else None
        es_detalle = siguiente is not None and (getattr(siguiente, "solo_detalle", False)
                                                or "codigo" in ((siguiente._datos or {}).get("payload") or {}))
        if url.endswith("/v2/compra-agil") and (siguiente is None or es_detalle):
            return _ok({"items": [], "paginacion": {"numero_pagina": 1, "total_paginas": 0, "total_resultados": 0}})
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


def _error(status, mensaje, solo_detalle=False):
    r = Resp(status, {"success": "NOK", "payload": None, "errors": [{"codigo": str(status), "mensaje": mensaje}]})
    r.solo_detalle = solo_detalle   # la cola falsa no se la entrega al listado
    return r


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


AHORA = datetime(2026, 10, 21, 12, 0)


def _actualizar(c, filtro=FILTRO, estado=None, **kw):
    estado = estado if estado is not None else estado_vacio()
    r = actualizar_compras_agiles(c, filtro, estado, dias_iniciales=1, ahora=AHORA, **kw)
    return r, estado


def test_ticket_va_en_el_encabezado_y_no_en_la_url():
    c = _cliente([_pagina(["A"], 1, 1)])
    items, cubierto = listar_publicadas(c, datetime(2026, 10, 21, 10, 30), AHORA, regiones=[13, 5])
    url, params, headers = c._sesion.llamadas[0]
    assert url == "https://api2.mercadopublico.cl/v2/compra-agil"
    assert headers == {"ticket": "SECRETO"}
    assert "SECRETO" not in json.dumps(params)
    assert params["estado"] == "publicada" and params["region"] == "13,5"
    # Una hora a la vez, primero la más antigua (sus compras cierran antes).
    assert params["publicado_desde"] == "2026-10-21T10:30:00Z" and params["publicado_hasta"] == "2026-10-21T11:29:59Z"
    ultima = c._sesion.llamadas[-1][1]
    assert ultima["publicado_desde"] == "2026-10-21T11:30:00Z" and ultima["publicado_hasta"] == "2026-10-21T12:00:00Z"
    assert len(c._sesion.llamadas) == 2 and cubierto == AHORA


def test_recorre_paginas_sin_repetidos():
    c = _cliente([_pagina(["A", "B"], 1, 2), _pagina(["B", "C"], 2, 2)])
    items, _ = listar_publicadas(c, datetime(2026, 10, 21), AHORA)
    assert [i["codigo"] for i in items] == ["A", "B", "C"]


def test_504_con_pagina_grande_sigue_con_paginas_de_10():
    c = _cliente([_error(504, "Gateway Timeout"), _pagina(["A"], 1, 1)])
    items, _ = listar_publicadas(c, datetime(2026, 10, 21, 11, 30), AHORA, tamano_pagina=50)
    assert [i["codigo"] for i in items] == ["A"]
    assert [ll[1]["tamano_pagina"] for ll in c._sesion.llamadas] == [50, 10]


def test_listado_cortado_por_tope_conserva_los_dias_mas_antiguos():
    c = _cliente([_pagina(["VIEJA"], 1, 1), _pagina(["NUEVA"], 1, 1)])
    items, cubierto = listar_publicadas(c, datetime(2026, 10, 21, 10), AHORA, max_paginas=1)
    assert [i["codigo"] for i in items] == ["VIEJA"]
    assert cubierto == datetime(2026, 10, 21, 10, 59, 59)   # la próxima corrida sigue desde ahí


def test_429_no_espera_mas_alla_del_plazo(monkeypatch):
    esperas = []
    monkeypatch.setattr(compra_agil.time, "sleep", esperas.append)
    c = _cliente([_error(429, "límite")])
    c.hasta_monotonic = compra_agil.time.monotonic() + 60   # quedan 60 s; la espera sería de 900
    with pytest.raises(ErrorApi):
        c.listado()
    assert 900 not in esperas


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
    _, estado = _actualizar(c)
    fila = estado["abiertas"]["X"]["fila"]
    assert fila["fecha_cierre"] == "2026-10-23 15:00:00" and fila["dias_restantes"] == 2


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


def test_clasifica_descarta_y_recuerda():
    pagina = _pagina(["A", "B", "C"], 1, 1)
    pagina._datos["payload"]["items"][1]["nombre"] = "Servicio de banquetería"
    c = _cliente([pagina, _detalle("A"),
                  # El listado decía «guantes», pero el detalle es otra cosa: se descarta.
                  _detalle("C", nombre="Servicio de banquetería", productos=[{"nombre": "Banquetería", "cantidad": 1}])])
    r, estado = _actualizar(c)
    assert r.listadas == 3 and r.nuevas_candidatas == 2   # B no pasa el filtro por nombre: sin detalle
    assert set(estado["abiertas"]) == {"A"} and set(estado["descartadas"]) == {"C"}
    fila = estado["abiertas"]["A"]["fila"]
    assert fila["tipo"] == "Compra Ágil" and fila["llamado"] == 1 and fila["rubro"] == "aseo"
    assert fila["url"] == "https://buscador.mercadopublico.cl/ficha?code=A"
    assert estado["listado_hasta"] == "2026-10-21T11:59:59" and not estado["pendientes"]

    # Corrida siguiente: lista desde la anterior (menos 1 h) y no vuelve a pedir detalles conocidos.
    c2 = _cliente([_pagina(["A", "D"], 1, 1), _detalle("D")])
    r2 = actualizar_compras_agiles(c2, FILTRO, estado, ahora=AHORA.replace(hour=15))
    primera = c2._sesion.llamadas[0][1]
    assert primera["publicado_desde"] == "2026-10-21T10:59:59Z"   # una hora de margen
    assert r2.detalles == 1 and "D" in estado["abiertas"]


def test_las_cerradas_salen_de_la_memoria():
    estado = estado_vacio()
    estado["abiertas"]["V"] = {"fila": {"fecha_cierre": "2026-10-21 10:00:00"}, "detalle": {}}
    estado["descartadas"]["W"] = "2026-10-20 18:00"
    estado["pendientes"]["X"] = "2026-10-25 18:00"
    c = _cliente([_detalle("X")])
    _actualizar(c, estado=estado)
    assert "V" not in estado["abiertas"] and "W" not in estado["descartadas"] and "X" in estado["abiertas"]


def test_sin_tiempo_quedan_pendientes_para_la_proxima():
    c = _cliente([_pagina(["A", "B"], 1, 1)])
    r, estado = _actualizar(c, max_detalles=0)
    assert set(estado["pendientes"]) == {"A", "B"} and r.detenida.startswith("máximo")


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
    r, estado = _actualizar(c)
    assert set(estado["abiertas"]) == {"A"} and set(estado["pendientes"]) == {"B"}
    assert "429" in r.detenida


def test_config_real_detecta_aseo():
    filtro = FiltroRubros.desde_config(cargar_config())
    c = _cliente([_pagina(["A"], 1, 1), _detalle("A", nombre="Adquisición de artículos de aseo", productos=[
        {"nombre": "Cloro", "descripcion": "cloro tradicional 5 litros", "cantidad": 10, "unidad_medida": "Unidad"},
        {"nombre": "Papel higiénico", "descripcion": "rollo 500 m", "cantidad": 24, "unidad_medida": "Unidad"}])])
    _, estado = _actualizar(c, filtro=filtro)
    assert [a["fila"]["rubro"] for a in estado["abiertas"].values()] == ["insumos_medicos_aseo"]


def test_detalle_504_no_se_reintenta_y_se_descarta_tras_tres_corridas():
    estado = estado_vacio()
    estado["pendientes"]["L"] = {"cierre": "2026-10-25 18:00", "intentos": 0, "prioridad": 0}
    for corrida in range(1, 4):
        c = _cliente([_error(504, "Endpoint request timed out", solo_detalle=True)])
        _actualizar(c, estado=estado)
        assert len([ll for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]) == 1   # sin reintentos
        if corrida < 3:
            assert estado["pendientes"]["L"]["intentos"] == corrida
    assert "L" not in estado["pendientes"] and "L" in estado["descartadas"]


def test_primero_las_que_calzan_por_nombre():
    pagina = _pagina(["GEN", "GUA"], 1, 1)
    pagina._datos["payload"]["items"][0]["nombre"] = "Compra de insumos varios"
    filtro = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes"],
                                    "palabras_candidatas": ["insumos"]}})
    c = _cliente([pagina, _detalle("GUA"), _detalle("GEN")])
    _actualizar(c, filtro=filtro)
    detalles = [ll[0].rsplit("/", 1)[1] for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]
    assert detalles == ["GUA", "GEN"]


def test_api_caida_corta_los_detalles():
    estado = estado_vacio()
    for n in range(20):
        estado["pendientes"][f"P{n}"] = {"cierre": "2026-10-25 18:00", "intentos": 0, "prioridad": 1}
    c = _cliente([_error(504, "timeout", solo_detalle=True) for _ in range(20)])
    r, _ = _actualizar(c, estado=estado)
    assert "sin respuesta" in r.detenida
    assert len([ll for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]) == compra_agil.MAX_FALLAS_SEGUIDAS
