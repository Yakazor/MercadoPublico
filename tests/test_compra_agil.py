import json
from datetime import datetime

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
        if getattr(self, "rechaza_cambios", False) and "cambio_desde" in params:
            return _error(400, "parámetro no soportado")
        siguiente = self.respuestas[0] if self.respuestas else None
        es_detalle = siguiente is not None and (getattr(siguiente, "solo_detalle", False)
                                                or "codigo" in ((siguiente._datos or {}).get("payload") or {}))
        # Una página marcada `solo_cambio` es del listado por último cambio: el de publicación no la toma.
        solo_cambio = getattr(siguiente, "solo_cambio", False) and "publicado_desde" in params
        if url.endswith("/v2/compra-agil") and (siguiente is None or es_detalle or solo_cambio):
            return _ok({"items": [], "paginacion": {"numero_pagina": 1, "total_paginas": 0, "total_resultados": 0}})
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(compra_agil.time, "sleep", lambda s: None)


def _cliente(respuestas):
    c = ClienteCompraAgil("SECRETO", pausa=0, reintentos=2)
    c._sesion = Sesion(respuestas)
    return c


def _cliente_sin_cambios(respuestas):
    """API que no acepta el listado por último cambio: se usa el respaldo (revisar una a una)."""
    c = _cliente(respuestas)
    c._sesion.rechaza_cambios = True
    return c


def _ok(payload):
    return Resp(200, {"success": "OK", "trace": None, "payload": payload, "errors": None})


def _error(status, mensaje, solo_detalle=False):
    r = Resp(status, {"success": "NOK", "payload": None, "errors": [{"codigo": str(status), "mensaje": mensaje}]})
    r.solo_detalle = solo_detalle   # la cola falsa no se la entrega al listado
    return r


def _pagina(codigos, pagina, total):
    return _ok({"items": [{"codigo": c, "nombre": f"Compra de guantes {c}",
                           "fechas": {"fecha_cierre": "2026-10-23T15:00:00Z"}} for c in codigos],
                "paginacion": {"numero_pagina": pagina, "total_paginas": total, "total_resultados": 9}})


def _detalle(codigo, nombre="Compra de guantes de nitrilo", productos=None, cierre="2026-10-23T15:00:00Z", llamado=1):
    return _ok({
        "codigo": codigo, "nombre": nombre, "descripcion": "Para el CESFAM",
        "estado": {"codigo": "publicada", "glosa": "Publicada"},
        "convocatoria": {"estado_convocatoria": llamado},
        "fechas": {"fecha_publicacion": "2026-10-20T10:00:00Z", "fecha_cierre": cierre},
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
    assert estado["cambios_hasta"] == "2026-10-21T11:59:59" and not estado["pendientes"]
    assert not estado["listado_hasta"]   # el listado por publicación es solo el respaldo

    # Corrida siguiente: lista desde la anterior (menos 1 h) y no vuelve a pedir detalles conocidos.
    c2 = _cliente([_pagina(["A", "D"], 1, 1), _detalle("D")])
    r2 = actualizar_compras_agiles(c2, FILTRO, estado, ahora=AHORA.replace(hour=15))
    primera = c2._sesion.llamadas[0][1]
    assert primera["cambio_desde"] == "2026-10-21T10:59:59Z"   # una hora de margen
    assert primera["ordenar_por"] == "FechaUltimaModificacion"
    assert r2.detalles == 1 and "D" in estado["abiertas"]


def test_las_cerradas_salen_de_la_memoria():
    estado = estado_vacio()
    estado["abiertas"]["V"] = {"fila": {"fecha_cierre": "2026-10-21 10:00:00"}, "detalle": {}}
    estado["descartadas"]["W"] = "2026-10-20 18:00"
    estado["pendientes"]["X"] = "2026-10-25 18:00"
    # V (sin llamado guardado) cerró: queda por revisar y su detalle sigue cerrado.
    c = _cliente([_detalle("V", cierre="2026-10-21T10:00:00Z"), _detalle("X")])
    _actualizar(c, estado=estado)
    assert "V" not in estado["abiertas"] and "W" not in estado["descartadas"] and "X" in estado["abiertas"]
    assert set(estado["por_revisar"]) == {"V"}


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


@pytest.mark.parametrize("nombre, producto", [
    ("20-224-600-003-00 TROCAR ATRAUMATICO 12MM CON PUNZON Y CAMISA REDUCTOR", "Trocares quirúrgicos"),
    ("SONDA FOLEY 2 VIAS N 8 CON BALON DE 5 CC", "Sondas quirúrgicas"),
    ("GIF CARD PARA TEXTILES, VESTUARIO Y CALZADO", "Tarjetas comerciales"),
    ("Servicio de Coctelería para mesas de coordinación", "Servicios de catering"),
    ("IONÓMERO DE VIDRIO MODIFICADO CON RESINA PARA USO COMO MATERIAL RESTAURADOR", "Unidades dentales"),
])
def test_falsos_positivos_de_la_auditoria_de_compras_agiles(nombre, producto):
    # Casos reales del 21-10-2026: palabras genéricas (camisa, balón, vidrio, mesas)
    # dentro de nombres de dispositivos clínicos o servicios.
    filtro = FiltroRubros.desde_config(cargar_config())
    assert not filtro.evaluar(nombre=nombre, items_onu=[producto], productos=[f"{producto} {nombre}"]).coincide


def test_las_guardadas_se_reclasifican_con_la_config_vigente():
    c = _cliente([_pagina(["A"], 1, 1), _detalle("A")])
    _, estado = _actualizar(c)
    assert "A" in estado["abiertas"]
    otro_filtro = FiltroRubros({"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes"],
                                         "excluir_en_nombre": ["nitrilo"]}})
    _actualizar(_cliente([]), filtro=otro_filtro, estado=estado)
    assert "A" not in estado["abiertas"] and "A" in estado["descartadas"]


def test_listado_caido_guarda_lo_recorrido_y_sigue_con_los_detalles():
    # 21-10-2026: el listado respondió 500/504 y la corrida se cortaba sin revisar
    # ninguna de las ~1.500 pendientes.
    estado = estado_vacio()
    estado["pendientes"]["P"] = {"cierre": "2026-10-25 18:00", "intentos": 0, "prioridad": 0}
    c = _cliente([_pagina(["A"], 1, 1), _error(500, "Servicio no disponible"), _error(504, "timeout"),
                  _error(504, "timeout"), _detalle("A"), _detalle("P")])
    r, estado = _actualizar(c, estado=estado)
    assert set(estado["abiertas"]) == {"P", "A"} and not estado["pendientes"]
    # Completa solo la primera hora: la próxima corrida retoma desde ahí.
    assert estado["cambios_hasta"] == "2026-10-20T12:59:59"
    assert r.listadas == 1 and "listado interrumpido" in r.detenida


def test_listado_con_ticket_rechazado_sigue_siendo_fatal():
    c = _cliente([_error(403, "El ticket no existe")])
    with pytest.raises(ErrorApi):
        _actualizar(c)


def test_primero_las_mas_recientes_y_no_las_que_cierran_en_menos_de_12_horas():
    # 22-10-2026: 401 de 403 Compras Ágiles publicadas cerraban esa misma mañana; se
    # revisaban primero las que cerraban antes, que ya no alcanzaban a cotizarse.
    estado = estado_vacio()
    estado["pendientes"] = {
        "VIEJA": {"cierre": "2026-10-23 10:00", "intentos": 0, "prioridad": 0, "publicado": "2026-10-20T09:00:00Z"},
        "NUEVA": {"cierre": "2026-10-23 15:00", "intentos": 0, "prioridad": 0, "publicado": "2026-10-21T11:00:00Z"},
        "SIN_FECHA": {"cierre": "2026-10-24 12:00", "intentos": 0, "prioridad": 0},   # formato anterior
        "YA_NO": {"cierre": "2026-10-21 20:00", "intentos": 0, "prioridad": 0, "publicado": "2026-10-21T11:30:00Z"},
    }
    c = _cliente([_detalle("SIN_FECHA"), _detalle("NUEVA"), _detalle("VIEJA")])
    _actualizar(c, estado=estado)
    detalles = [ll[0].rsplit("/", 1)[1] for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]
    assert detalles == ["SIN_FECHA", "NUEVA", "VIEJA"]
    assert "YA_NO" not in estado["pendientes"] and "YA_NO" not in estado["abiertas"]


def test_la_pendiente_guarda_la_fecha_de_publicacion():
    pagina = _ok({"items": [{"codigo": "A", "nombre": "Compra de guantes", "fechas": {
        "fecha_publicacion": "2026-10-21T10:00:00Z", "fecha_cierre": "2026-10-25T15:00:00Z"}}],
        "paginacion": {"numero_pagina": 1, "total_paginas": 1, "total_resultados": 1}})
    c = _cliente([pagina, _error(429, "límite", solo_detalle=True), _error(429, "límite", solo_detalle=True)])
    _, estado = _actualizar(c)
    assert estado["pendientes"]["A"]["publicado"] == "2026-10-21T10:00:00Z"


# --- 2º llamado (18-11-2026: desde el 25-10 no apareció ninguna; la misma compra se reabre con
# su código y fecha de publicación, y el listado por fecha de publicación no la volvía a traer).

def _cerrada_primer_llamado(codigo="A", cierre="2026-10-21 10:00:00"):
    estado = estado_vacio()
    estado["abiertas"][codigo] = {"fila": {"fecha_cierre": cierre, "llamado": 1}, "detalle": {}}
    return estado


def test_la_cerrada_en_primer_llamado_vuelve_si_se_abre_el_segundo():
    estado = _cerrada_primer_llamado()
    c = _cliente_sin_cambios([_detalle("A", cierre="2026-10-21T10:00:00Z")])     # todavía cerrada
    r, _ = _actualizar(c, estado=estado)
    assert "A" not in estado["abiertas"] and estado["por_revisar"]["A"]["revisada"] == "2026-10-21T12:00:00"
    assert r.revisadas == 1 and r.reabiertas == 0

    # Antes de 6 horas no se vuelve a preguntar.
    c = _cliente_sin_cambios([])
    actualizar_compras_agiles(c, FILTRO, estado, ahora=AHORA.replace(hour=15))
    assert not [ll for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]

    # Al día siguiente la API la muestra abierta en 2º llamado.
    c = _cliente_sin_cambios([_detalle("A", cierre="2026-10-24T15:00:00Z", llamado=2)])
    r = actualizar_compras_agiles(c, FILTRO, estado, ahora=AHORA.replace(day=22))
    fila = estado["abiertas"]["A"]["fila"]
    assert r.reabiertas == 1 and fila["llamado"] == 2 and fila["fecha_cierre"].startswith("2026-10-24")
    assert "A" not in estado["por_revisar"]


def test_por_revisar_vence_a_los_tres_dias():
    estado = _cerrada_primer_llamado()
    _actualizar(_cliente_sin_cambios([_detalle("A", cierre="2026-10-21T10:00:00Z")]), estado=estado)
    c = _cliente_sin_cambios([])
    actualizar_compras_agiles(c, FILTRO, estado, ahora=AHORA.replace(day=24, hour=11))
    assert "A" not in estado["por_revisar"]
    assert not [ll for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]


def test_la_de_segundo_llamado_que_cierra_no_se_revisa():
    estado = _cerrada_primer_llamado()
    estado["abiertas"]["A"]["fila"]["llamado"] = 2
    c = _cliente([])
    _actualizar(c, estado=estado)
    assert not estado["por_revisar"] and not estado["abiertas"]


def test_reaparece_en_el_listado_con_otro_cierre():
    estado = estado_vacio()
    estado["abiertas"]["A"] = {"fila": {"fecha_cierre": "2026-10-22 10:00:00", "llamado": 1}, "detalle": {}}
    c = _cliente([_pagina(["A"], 1, 1), _detalle("A", cierre="2026-10-23T15:00:00Z", llamado=2)])
    r, _ = _actualizar(c, estado=estado)
    assert r.reabiertas == 1 and estado["abiertas"]["A"]["fila"]["llamado"] == 2


def test_la_candidata_por_nombre_que_cierra_sin_detalle_tambien_se_revisa():
    estado = estado_vacio()
    estado["pendientes"]["P"] = {"cierre": "2026-10-21 18:00", "intentos": 0, "prioridad": 0}
    estado["pendientes"]["Q"] = {"cierre": "2026-10-21 18:00", "intentos": 0, "prioridad": 1}
    _actualizar(_cliente_sin_cambios([]), estado=estado)
    assert set(estado["por_revisar"]) == {"P"} and not estado["pendientes"]
    # No se pregunta antes de su cierre (18:00).
    c = _cliente_sin_cambios([_detalle("P", cierre="2026-10-23T15:00:00Z", llamado=2)])
    r = actualizar_compras_agiles(c, FILTRO, estado, ahora=AHORA.replace(hour=19))
    assert r.reabiertas == 1 and estado["abiertas"]["P"]["fila"]["llamado"] == 2


def test_429_al_revisar_corta_y_queda_para_la_proxima():
    estado = _cerrada_primer_llamado()
    c = _cliente_sin_cambios([_error(429, "límite", solo_detalle=True), _error(429, "límite", solo_detalle=True)])
    r, _ = _actualizar(c, estado=estado)
    assert "429" in r.detenida and estado["por_revisar"]["A"]["revisada"] is None



# --- Listado por fecha de último cambio (18-11-2026: «en Mercado Público hay hartas de 2º llamado») ---

def _fila(codigo, llamado, cierre="2026-10-23T15:00:00Z", nombre=None):
    return {"codigo": codigo, "nombre": nombre or f"Compra de guantes {codigo}",
            "convocatoria": {"estado_convocatoria": llamado, "descripcion": f"{llamado} llamado"},
            "fechas": {"fecha_publicacion": "2026-10-15T10:00:00Z", "fecha_cierre": cierre}}


def _pagina_filas(filas):
    r = _ok({"items": filas, "paginacion": {"numero_pagina": 1, "total_paginas": 1, "total_resultados": len(filas)}})
    r.solo_cambio = True
    return r


def test_lista_tambien_por_ultimo_cambio_y_trae_las_de_segundo_llamado():
    # La de 2º llamado se publicó hace días: no sale en el listado por publicación (vacío),
    # sí en el de cambios; su detalle se pide antes que el de la de 1er llamado.
    c = _cliente([_pagina_filas([_fila("UNO", 1), _fila("DOS", 2)]),
                  _detalle("DOS", llamado=2), _detalle("UNO")])
    r, estado = _actualizar(c)
    params = [ll[1] for ll in c._sesion.llamadas if ll[0].endswith("/v2/compra-agil")]
    con_filas = [p for p in params if "cambio_desde" in p and p["numero_pagina"] == 1]
    assert con_filas and all(p["ordenar_por"] == "FechaUltimaModificacion" for p in con_filas)
    assert all("publicado_desde" in p for p in params if "cambio_desde" not in p)
    detalles = [ll[0].rsplit("/", 1)[1] for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]
    assert detalles == ["DOS", "UNO"] and r.segundo_llamado == 1
    assert estado["abiertas"]["DOS"]["fila"]["llamado"] == 2 and estado["cambios_hasta"]


def test_la_abierta_que_pasa_a_segundo_llamado_se_vuelve_a_pedir():
    estado = estado_vacio()
    estado["abiertas"]["A"] = {"fila": {"fecha_cierre": "2026-10-23 15:00:00", "llamado": 1}, "detalle": {}}
    c = _cliente([_pagina_filas([_fila("A", 2)]), _detalle("A", llamado=2)])
    r, _ = _actualizar(c, estado=estado)
    assert estado["abiertas"]["A"]["fila"]["llamado"] == 2


def test_la_de_segundo_llamado_se_revisa_aunque_cierre_en_pocas_horas():
    c = _cliente([_pagina_filas([_fila("DOS", 2, cierre="2026-10-21T18:00:00Z"),
                                           _fila("UNO", 1, cierre="2026-10-21T18:00:00Z")]),
                  _detalle("DOS", llamado=2, cierre="2026-10-21T18:00:00Z")])
    _, estado = _actualizar(c)
    assert "DOS" in estado["abiertas"] and "UNO" not in estado["abiertas"]


def test_si_la_api_rechaza_el_listado_por_cambios_sigue_como_antes():
    c = _cliente([_error(400, "parámetro inválido"), _pagina(["A"], 1, 1), _detalle("A")])
    r, estado = _actualizar(c)
    assert "A" in estado["abiertas"] and not r.detenida and not estado["cambios_hasta"]
    params = [ll[1] for ll in c._sesion.llamadas if ll[0].endswith("/v2/compra-agil")]
    assert "cambio_desde" in params[0] and "publicado_desde" in params[1]
    assert estado["listado_hasta"]


def test_si_la_api_ignora_el_filtro_de_cambios_lista_por_publicacion():
    # Responde 200 pero con filas de otra fecha: el filtro no se aplicó.
    vieja = _pagina_filas([_fila("X", 1) | {"fechas": {"fecha_cierre": "2026-10-23T15:00:00Z",
                                                       "fecha_ultimo_cambio": "2026-09-01T10:00:00Z"}}])
    vieja.solo_cambio = False
    c = _cliente([vieja, _pagina(["A"], 1, 1), _detalle("A")])
    r, estado = _actualizar(c)
    assert "A" in estado["abiertas"] and "X" not in estado["pendientes"] and estado["listado_hasta"]



def test_sin_emt_no_pide_el_detalle_de_las_de_primer_llamado():
    # 18-11-2026: 417 consultas se fueron en listar y pedir detalles de 1er llamado, y la API
    # cortó (HTTP 429) antes de llegar a las de 2º llamado.
    estado = estado_vacio()
    estado["pendientes"]["VIEJA1"] = {"cierre": "2026-10-23 15:00", "intentos": 0, "prioridad": 0, "llamado": 1}
    c = _cliente([_pagina_filas([_fila("UNO", 1), _fila("DOS", 2), _fila("SIN", None)]),
                  _detalle("DOS", llamado=2), _detalle("SIN")])
    r, _ = _actualizar(c, estado=estado, solo_segundo_llamado=True)
    detalles = [ll[0].rsplit("/", 1)[1] for ll in c._sesion.llamadas if "/v2/compra-agil/" in ll[0]]
    assert detalles == ["DOS", "SIN"] and r.saltadas_primer_llamado == 1
    assert "VIEJA1" not in estado["pendientes"] and "UNO" not in estado["pendientes"]
