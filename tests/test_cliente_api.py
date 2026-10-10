import pytest

from radar import cliente_api
from radar.cliente_api import ClienteMercadoPublico, ErrorApi


class Resp:
    def __init__(self, status, datos):
        self.status_code, self._datos, self.text = status, datos, str(datos)
        self.ok = status < 400

    def json(self):
        return self._datos


class Sesion:
    def __init__(self, respuestas):
        self.respuestas, self.llamadas = list(respuestas), []

    def get(self, url, params, timeout):
        self.llamadas.append(params)
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(cliente_api.time, "sleep", lambda s: None)


def _cliente(respuestas, reintentos=3):
    c = ClienteMercadoPublico("SECRETO", pausa=0, reintentos=reintentos)
    c._sesion = Sesion(respuestas)
    return c


def test_reintenta_errores_temporales_y_luego_responde():
    c = _cliente([
        Resp(500, {"Codigo": 10500, "Mensaje": "Lo sentimos. Hemos detectado que existen peticiones simultáneas."}),
        Resp(429, None),
        Resp(200, {"Cantidad": 1, "Listado": [{"CodigoExterno": "A"}]}),
    ])
    assert c.licitaciones(estado="activas")["Listado"][0]["CodigoExterno"] == "A"
    assert len(c._sesion.llamadas) == 3
    assert c._sesion.llamadas[0]["ticket"] == "SECRETO"


def test_error_definitivo_no_reintenta_ni_expone_ticket():
    c = _cliente([Resp(400, {"Codigo": 203, "Mensaje": "Ticket no válido."})])
    with pytest.raises(ErrorApi) as e:
        c.licitaciones(codigo="X")
    assert "Ticket no válido" in str(e.value) and "SECRETO" not in str(e.value)
    assert len(c._sesion.llamadas) == 1


def test_agota_reintentos():
    c = _cliente([Resp(503, None)] * 3, reintentos=2)
    with pytest.raises(ErrorApi, match="2 reintentos"):
        c.ordenes_de_compra(fecha="01102026")
