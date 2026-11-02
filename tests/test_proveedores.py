import base64
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from radar import proveedores as prov

RAIZ = Path(__file__).resolve().parents[1]
CFG = prov.CONFIG
LIC = {"codigo": "2-2-COT26", "nombre": "Mochilas escolares", "organismo": "Municipalidad de Lo Prado",
       "tipo": "Compra Ágil", "region": "Región Metropolitana de Santiago", "comuna": "Lo Prado",
       "direccion_entrega": "Av. San Pablo 5959", "fecha_cierre": "2026-11-10 15:00:00", "plazo_entrega_dias": 5.0}
ITEMS = [
    {"linea": 1, "producto": "Mochilas", "descripcion": "MOCHILA ESCOLAR 30 L", "cantidad": 15, "unidad": "EA"},
    {"linea": 2, "producto": "Estuches", "descripcion": "Estuche escolar", "cantidad": 15, "unidad": "EA"},
]


def test_depurar_solo_deja_contactos_que_aparecen_en_paginas_leidas():
    texto = "Contacto: ventas@mochilas.cl · Fono +56 2 2345 6789"
    urls = {"https://www.mochilas.cl/contacto", "https://otra.cl/x"}
    limpio = prov.depurar([
        {"nombre": "Mochilas Chile", "correo": "ventas@mochilas.cl", "telefono": "(2) 2345 6789",
         "fuente": "https://www.mochilas.cl/contacto", "web": "https://www.mochilas.cl", "lineas": [1, 1, 2]},
        {"nombre": "Inventado", "correo": "contacto@inventado.cl", "telefono": "+56 9 1111 2222",
         "fuente": "https://inventado.cl", "web": "inventado.cl", "lineas": [2], "nota": "Mayorista"},
        {"nombre": "", "correo": None},
    ], texto, urls)
    assert [p["nombre"] for p in limpio] == ["Mochilas Chile", "Inventado"]
    bueno, malo = limpio
    assert (bueno["correo"], bueno["telefono"], bueno["verificado"], bueno["lineas"]) == (
        "ventas@mochilas.cl", "(2) 2345 6789", True, [1, 2])
    assert malo["correo"] is None and malo["telefono"] is None and malo["web"] is None
    assert malo["verificado"] is False
    assert malo["nota"] == "Mayorista; correo por confirmar; teléfono por confirmar"


class _Bloque(SimpleNamespace):
    def model_dump(self):
        def a_dict(v):
            if isinstance(v, SimpleNamespace):
                return {k: a_dict(x) for k, x in vars(v).items()}
            if isinstance(v, list):
                return [a_dict(x) for x in v]
            return v
        return a_dict(self)


def _respuesta(bloques, stop="end_turn", busquedas=2):
    uso = SimpleNamespace(input_tokens=20_000, output_tokens=3_000, cache_read_input_tokens=0,
                          server_tool_use=SimpleNamespace(web_search_requests=busquedas))
    return SimpleNamespace(content=bloques, stop_reason=stop, usage=uso, model="claude-opus-5-5")


class _Cliente:
    """Devuelve las respuestas en orden; una excepción en la lista se lanza (p. ej. un 400 de la API)."""
    def __init__(self, respuestas):
        self.respuestas, self.pedidos = list(respuestas), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: self._crear("beta", **k)))
        self.messages = SimpleNamespace(create=lambda **k: self._crear("normal", **k))

    def _crear(self, via, **k):
        self.pedidos.append(k | {"via": via})
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Rechazo(Exception):
    pass


def test_buscar_arma_el_pedido_reanuda_pausas_y_depura(monkeypatch):
    resultado_json = json.dumps({"resumen": "Fácil de abastecer.", "proveedores": [
        {"nombre": "Mochilas Chile", "tipo": "distribuidor mayorista", "lineas": [1], "productos": "Mochilas",
         "web": "https://www.mochilas.cl", "correo": "ventas@mochilas.cl", "telefono": None, "ciudad": "Santiago",
         "fuente": "https://www.mochilas.cl/contacto", "nota": None},
        {"nombre": "Sin respaldo", "tipo": "tienda", "lineas": [2], "productos": "Estuches",
         "web": "https://x.cl", "correo": "hola@x.cl", "telefono": None, "ciudad": None,
         "fuente": "https://x.cl", "nota": None}]})
    pausa = _respuesta([
        _Bloque(type="server_tool_use", name="web_search", input={"query": "mochilas mayorista"}),
        _Bloque(type="web_search_tool_result", content=[_Bloque(type="web_search_result",
                                                                url="https://www.mochilas.cl/contacto")]),
    ], stop="pause_turn")
    final = _respuesta([
        _Bloque(type="web_fetch_tool_result", content=_Bloque(
            type="web_fetch_result", url="https://www.mochilas.cl/contacto",
            content=_Bloque(type="document", source=_Bloque(type="text", data="Escríbenos a ventas@mochilas.cl")))),
        _Bloque(type="text", text=resultado_json),
    ], busquedas=1)
    cliente = _Cliente([pausa, final])
    r = prov.buscar(LIC, ITEMS, "clave", CFG, cliente=cliente, ahora=datetime(2026, 11, 2, 10, 0, tzinfo=prov.CHILE))

    assert len(cliente.pedidos) == 2                                    # reanudó el «pause_turn»
    pedido = cliente.pedidos[0]
    assert pedido["model"] == "claude-opus-5-5" and pedido["fallbacks"] == "default"
    assert pedido["output_config"]["format"]["schema"] == prov.ESQUEMA
    assert {h["name"] for h in pedido["tools"]} == {"web_search", "web_fetch"}
    texto = pedido["messages"][0]["content"]
    assert "Línea 1: Mochilas — MOCHILA ESCOLAR 30 L (15 EA)" in texto and "Av. San Pablo 5959" in texto
    assert cliente.pedidos[1]["messages"][-1]["role"] == "assistant"   # la pausa se reenvía tal cual

    assert r["codigo"] == "2-2-COT26" and r["busquedas"] == 3 and r["resumen"] == "Fácil de abastecer."
    assert r["costo_usd"] == round((40_000 * 4 + 6_000 * 20) / 1e6 + 3 * 0.01, 2)
    assert r["proveedores"][0]["correo"] == "ventas@mochilas.cl" and r["proveedores"][0]["verificado"]
    assert r["proveedores"][1]["correo"] is None                      # no se leyó en ninguna página


def test_si_la_api_rechaza_las_opciones_reintenta_mas_simple(monkeypatch):
    monkeypatch.setattr(prov, "_rechazos", lambda: (_Rechazo,))
    texto = 'Listo. {"resumen": "ok", "proveedores": []} Saludos'
    cliente = _Cliente([_Rechazo("fallbacks"), _Rechazo("format"), _respuesta([_Bloque(type="text", text=texto)])])
    r = prov.buscar(LIC, ITEMS, "c", CFG, cliente=cliente)
    assert [p["via"] for p in cliente.pedidos] == ["beta", "normal", "normal"]
    assert "fallbacks" not in cliente.pedidos[1] and "format" not in cliente.pedidos[2]["output_config"]
    assert "Responde solo con un objeto JSON" in cliente.pedidos[2]["messages"][0]["content"]
    assert r["resumen"] == "ok" and r["proveedores"] == []
    with pytest.raises(prov.ErrorBusqueda, match="no aceptó"):
        prov.buscar(LIC, ITEMS, "c", CFG, cliente=_Cliente([_Rechazo(), _Rechazo(), _Rechazo()]))


def test_buscar_rechazo_o_respuesta_ilegible_avisa():
    with pytest.raises(prov.ErrorBusqueda, match="rechazó"):
        prov.buscar(LIC, ITEMS, "c", CFG, cliente=_Cliente([_respuesta([], stop="refusal")]))
    with pytest.raises(prov.ErrorBusqueda, match="No se pudo leer"):
        prov.buscar(LIC, ITEMS, "c", CFG, cliente=_Cliente([_respuesta([_Bloque(type="text", text="hola")])]))


def test_solicitud_pide_las_lineas_del_proveedor_con_entrega_y_plazo():
    remitente = {"empresa": "Comercial X", "nombre": "Ana", "cargo": "Ventas", "contacto": "+56 9 1234 5678"}
    proveedor = {"nombre": "Mochilas Chile", "correo": "ventas@mochilas.cl", "lineas": [1]}
    c = prov.solicitud(LIC, ITEMS, proveedor, remitente, date(2026, 11, 2))
    assert c["para"] == "ventas@mochilas.cl"
    assert c["asunto"] == "Solicitud de cotización – 2-2-COT26 – Mochilas escolares"
    assert "1. MOCHILA ESCOLAR 30 L — Cantidad: 15 EA" in c["cuerpo"]
    assert "stuche" not in c["cuerpo"]                              # solo las líneas que cubre
    assert "una Compra Ágil de Mercado Público (2-2-COT26) de Municipalidad de Lo Prado" in c["cuerpo"]
    assert "entrega en 5 días desde la orden de compra" in c["cuerpo"]
    assert "antes del 05-11-2026" in c["cuerpo"] and "cierra el 10-11-2026" in c["cuerpo"]
    assert c["cuerpo"].endswith("Ana\nVentas\nComercial X\n+56 9 1234 5678")
    todas = prov.solicitud(LIC, ITEMS, None, remitente, date(2026, 11, 2))
    assert todas["para"] == "" and "Estimados/as [Proveedor]" in todas["cuerpo"] and "2. Estuche escolar — Cantidad: 15 EA" in todas["cuerpo"]
    elegidas = prov.solicitud(LIC, ITEMS, proveedor, remitente, date(2026, 11, 2), lineas=[2])
    assert "1. Estuche escolar" in elegidas["cuerpo"] and "MOCHILA" not in elegidas["cuerpo"]

    gmail = parse_qs(urlsplit(prov.enlace_gmail(c)).query)
    assert gmail["to"] == ["ventas@mochilas.cl"] and gmail["su"] == [c["asunto"]] and gmail["body"] == [c["cuerpo"]]
    assert prov.enlace_correo(c).startswith("mailto:ventas%40mochilas.cl?subject=Solicitud%20de%20cotizaci")


class _R:
    def __init__(self, status, datos=None):
        self.status_code, self._datos = status, datos or {}

    def json(self):
        return self._datos


def test_guardar_crea_la_rama_huerfana_y_escribe_el_json(monkeypatch):
    pedidos = []

    def get(url, **k):
        pedidos.append(("GET", url))
        return _R(404)

    def post(url, json=None, **k):
        pedidos.append(("POST", url, json))
        return _R(201, {"sha": "abc"})

    def put(url, json=None, **k):
        pedidos.append(("PUT", url, json))
        return _R(201)

    monkeypatch.setattr(prov.requests, "get", get)
    monkeypatch.setattr(prov.requests, "post", post)
    monkeypatch.setattr(prov.requests, "put", put)
    prov.guardar("2-2-COT26", {"proveedores": [{"nombre": "Ñandú"}]}, "token", rama="proveedores")
    creados = [p[1].rsplit("/", 1)[-1] for p in pedidos if p[0] == "POST"]
    assert creados == ["blobs", "trees", "commits", "refs"]
    assert next(p[2] for p in pedidos if p[1].endswith("/commits"))["parents"] == []     # huérfana
    put_ = next(p for p in pedidos if p[0] == "PUT")
    assert put_[1].endswith("/contents/proveedores/2-2-COT26.json") and put_[2]["branch"] == "proveedores"
    assert json.loads(base64.b64decode(put_[2]["content"])) == {"proveedores": [{"nombre": "Ñandú"}]}
    assert "sha" not in put_[2]
    with pytest.raises(prov.ErrorGitHub, match="Falta el token"):
        prov.guardar("2-2-COT26", {}, None)


def test_guardar_reemplaza_con_el_sha_y_avisa_sin_permiso(monkeypatch):
    puts = []
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(200, {"sha": "viejo"}))
    monkeypatch.setattr(prov.requests, "put", lambda url, json=None, **k: puts.append(json) or _R(200))
    prov.guardar("1-1-LE26", {}, "token", rama="proveedores")
    assert puts[0]["sha"] == "viejo"
    monkeypatch.setattr(prov.requests, "put", lambda url, **k: _R(403))
    with pytest.raises(prov.ErrorGitHub, match="Contents: Read and write"):
        prov.guardar("1-1-LE26", {}, "token", rama="proveedores")


def test_leer_devuelve_la_busqueda_o_none(monkeypatch):
    guardada = {"codigo": "1", "proveedores": []}
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(200, guardada))
    assert prov.leer("1", rama="proveedores") == guardada
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(200, {"workflow_runs": []}))
    assert prov.leer("1", rama="proveedores") is None                # otra cosa: no es una búsqueda
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(404))
    assert prov.leer("1", rama="proveedores") is None

    def caido(url, **k):
        raise prov.requests.ConnectionError("sin red")
    monkeypatch.setattr(prov.requests, "get", caido)
    assert prov.leer("1", rama="proveedores") is None


# --- En la plataforma -------------------------------------------------------------------------

def _datos():
    lic = {"codigo": "1-1-LE26", "nombre": "Sillas de oficina", "organismo": "Municipalidad", "tipo": "LE",
           "region": "Región Metropolitana de Santiago", "monto_estimado": 2_000_000, "moneda": "CLP",
           "fecha_cierre": "2099-01-01 12:00:00", "dias_restantes": 7, "rubro_nombre": "Mobiliario",
           "url": "https://x/1-1-LE26"}
    return {"licitaciones": [lic], "items": [
        {"codigo": "1-1-LE26", "linea": 1, "producto": "Silla", "descripcion": "Silla ergonómica", "cantidad": 10,
         "unidad": "Unidad", "ref_mediana": 60_000}], "mercado": [], "meta": [{"generado": "2026-10-23T12:44:58-03:00"}]}


def _ficha(raiz: str) -> None:
    import sys

    sys.path.insert(0, raiz + "/plataforma")
    import comun
    import explorar

    prep = comun.datos()
    explorar.ficha(prep["licitaciones"][0], prep)


ENCONTRADOS = {"codigo": "1-1-LE26", "fecha": "2026-11-02T10:00-03:00", "busquedas": 3, "costo_usd": 0.31,
               "resumen": "Hay varios distribuidores en Santiago.", "proveedores": [
                   {"nombre": "Sillas Pro", "tipo": "fabricante", "lineas": [1], "productos": "Sillas de oficina",
                    "web": "https://sillaspro.cl", "correo": "ventas@sillaspro.cl", "telefono": None,
                    "ciudad": "Santiago", "fuente": "https://sillaspro.cl/contacto", "nota": None, "verificado": True}]}


@pytest.fixture
def plataforma(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    for nombre, valor in _datos().items():
        (tmp_path / f"{nombre}.json").write_text(json.dumps(valor), encoding="utf-8")
    monkeypatch.setenv("RADAR_DATOS", str(tmp_path))
    monkeypatch.setattr(prov, "leer", lambda codigo, **k: None)    # sin red: nada guardado
    guardados = []
    monkeypatch.setattr(prov, "guardar", lambda codigo, datos, token, **k: guardados.append((codigo, token)))
    return guardados


def test_ficha_sin_clave_de_claude_muestra_como_activarla_y_el_correo(plataforma):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_ficha, args=(str(RAIZ),), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("anthropic_api_key" in i.value for i in at.info)
    assert at.code[-1].value.startswith("Estimados/as [Proveedor]:")
    assert "1. Silla ergonómica — Cantidad: 10 Unidad" in at.code[-1].value


def test_ficha_busca_sola_al_abrir_guarda_y_arma_el_correo(plataforma, monkeypatch):
    from streamlit.testing.v1 import AppTest

    llamadas = []
    monkeypatch.setattr(prov, "buscar", lambda lic, items, clave, cfg=None, **k: llamadas.append(clave) or ENCONTRADOS)
    at = AppTest.from_function(_ficha, args=(str(RAIZ),), default_timeout=60)
    at.secrets["anthropic_api_key"] = "sk-prueba"
    at.secrets["github_token"] = "gh-prueba"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert llamadas == ["sk-prueba"] and plataforma == [("1-1-LE26", "gh-prueba")]
    tabla = at.dataframe[-1].value
    assert list(tabla["Proveedor"]) == ["Sillas Pro"] and list(tabla["Correo"]) == ["ventas@sillaspro.cl"]
    assert at.text_input[0].value == "ventas@sillaspro.cl"            # «Para» del correo
    assert at.code[-1].value.startswith("Estimados/as Sillas Pro:")
    at.run()                                                         # otra corrida: no vuelve a pagar la búsqueda
    assert llamadas == ["sk-prueba"]
