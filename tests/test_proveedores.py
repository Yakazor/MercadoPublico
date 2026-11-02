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


def test_guardar_crea_la_rama_huerfana_y_escribe_el_json_y_el_indice_de_precios(monkeypatch):
    pedidos, creada = [], []

    def get(url, **k):
        pedidos.append(("GET", url))
        return _R(200, {}) if creada and "/branches/" in url else _R(404)

    def post(url, json=None, **k):
        pedidos.append(("POST", url, json))
        if url.endswith("/refs"):
            creada.append(True)
        return _R(201, {"sha": "abc"})

    def put(url, json=None, **k):
        pedidos.append(("PUT", url, json))
        return _R(201)

    monkeypatch.setattr(prov.requests, "get", get)
    monkeypatch.setattr(prov.requests, "post", post)
    monkeypatch.setattr(prov.requests, "put", put)
    precio = {"linea": 1, "tienda": "Ñandú", "precio_unitario_neto": 100.0}
    datos = {"proveedores": [{"nombre": "Ñandú"}], "precios": [precio]}
    prov.guardar("2-2-COT26", datos, "token", rama="proveedores")
    creados = [p[1].rsplit("/", 1)[-1] for p in pedidos if p[0] == "POST"]
    assert creados == ["blobs", "trees", "commits", "refs"]                      # la rama se crea una vez
    assert next(p[2] for p in pedidos if p[1].endswith("/commits"))["parents"] == []     # huérfana
    puts = [p for p in pedidos if p[0] == "PUT"]
    assert puts[0][1].endswith("/contents/proveedores/2-2-COT26.json") and puts[0][2]["branch"] == "proveedores"
    assert json.loads(base64.b64decode(puts[0][2]["content"])) == datos
    assert "sha" not in puts[0][2]
    assert puts[1][1].endswith("/contents/proveedores/precios.json")
    assert json.loads(base64.b64decode(puts[1][2]["content"])) == {"2-2-COT26": [precio]}
    with pytest.raises(prov.ErrorGitHub, match="Falta el token"):
        prov.guardar("2-2-COT26", {}, None)


def test_indice_de_precios_conserva_otras_licitaciones_y_reintenta_si_otra_sesion_escribio(monkeypatch):
    previo = {"9-9-LE26": [{"linea": 1}], "2-2-COT26": [{"linea": 7}]}
    contenido = base64.b64encode(json.dumps(previo).encode()).decode()
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(200, {"sha": "s", "content": contenido}))
    puts, respuestas = [], [_R(200), _R(409), _R(200)]       # el índice choca una vez con otra sesión
    monkeypatch.setattr(prov.requests, "put", lambda url, json=None, **k: puts.append((url, json))
                        or respuestas.pop(0))
    prov.guardar("2-2-COT26", {"proveedores": [], "precios": []}, "token", rama="proveedores")
    indices = [json.loads(base64.b64decode(j["content"])) for u, j in puts if u.endswith("precios.json")]
    assert len(indices) == 2 and indices[-1] == {"9-9-LE26": [{"linea": 1}]}    # sin precios: sale del índice


def test_guardar_reemplaza_con_el_sha_y_avisa_sin_permiso(monkeypatch):
    puts = []
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(200, {"sha": "viejo"}))
    monkeypatch.setattr(prov.requests, "put", lambda url, json=None, **k: puts.append(json) or _R(200))
    prov.guardar("1-1-LE26", {}, "token", rama="proveedores")
    assert puts[0]["sha"] == "viejo"
    monkeypatch.setattr(prov.requests, "put", lambda url, **k: _R(403))
    with pytest.raises(prov.ErrorGitHub, match="Contents: Read and write"):
        prov.guardar("1-1-LE26", {}, "token", rama="proveedores")


def test_leer_precios_tolera_lo_que_no_es_indice(monkeypatch):
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(200, {"1": [{"linea": 1}, "x"], "2": "y"}))
    assert prov.leer_precios(rama="proveedores") == {"1": [{"linea": 1}]}
    monkeypatch.setattr(prov.requests, "get", lambda url, **k: _R(404))
    assert prov.leer_precios(rama="proveedores") == {}


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
    # Las cachés de la plataforma viven en el proceso: se limpian para que una prueba no vea
    # las búsquedas de otra.
    monkeypatch.syspath_prepend(str(RAIZ / "plataforma"))
    import cotizar
    cotizar._memoria().clear()
    cotizar._automaticas().clear()
    cotizar._guardado.clear()
    monkeypatch.setattr(prov, "leer_precios", lambda **k: {})
    cotizar.comun._indice_precios.clear()
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


# --- Auditoría (02-11): casos que dejaban pasar datos inventados o rompían la ficha ------------------

def test_evidencia_no_cuenta_lo_que_escribio_claude_ni_el_contenido_cifrado():
    bloques = [
        _Bloque(type="server_tool_use", name="web_search", input={"query": "ventas@inventado.cl 22223333"}),
        _Bloque(type="web_search_tool_result", content=[_Bloque(
            type="web_search_result", url="https://real.cl", title="Real", encrypted_content="QWx9 87654321 abc")]),
        _Bloque(type="text", text="Escriban a ventas@inventado.cl"),
    ]
    texto, urls = prov.evidencia(bloques)
    assert urls == {"https://real.cl"} and "Real" in texto
    assert "inventado" not in texto and "87654321" not in texto
    limpio = prov.depurar([{"nombre": "X", "correo": "ventas@inventado.cl", "telefono": "+56 2 8765 4321",
                            "fuente": "https://real.cl"}], texto, urls)[0]
    assert limpio["correo"] is None and limpio["telefono"] is None


def test_correo_completo_y_telefono_en_un_mismo_texto():
    texto = "Contacto: contacto@empresa.cl\nPrecio $12.345\nCódigo 678"
    assert prov._correo_en("contacto@empresa.cl", texto)
    assert not prov._correo_en("to@empresa.cl", texto)              # está dentro de otro correo
    assert not prov._telefono_en("+56 9 1234 5678", texto)           # cifras de precio y código juntas
    assert prov._telefono_en("+56 9 1234 5678", "Fono: +56 9 1234-5678")
    assert prov._telefono_en("(2) 2345 6789", "Llámanos al 2 2345 6789")


def test_depurar_tolera_respuestas_sin_el_formato_esperado():
    limpio = prov.depurar(["texto suelto", {"nombre": "Y", "lineas": ["1-3", 2, "4"], "correo": 5}], "", set())
    assert [p["nombre"] for p in limpio] == ["Y"]
    assert limpio[0]["lineas"] == [2, 4] and limpio[0]["correo"] is None


def test_solicitud_con_fecha_de_cierre_mal_formada():
    c = prov.solicitud(LIC | {"fecha_cierre": "2026-11-1 15:00"}, ITEMS, None, {}, date(2026, 11, 2))
    assert "el proceso cierra el próximamente" in c["cuerpo"]


def test_el_correo_de_la_rutina_usa_el_mismo_plazo_de_respuesta():
    import sys
    sys.path.insert(0, str(RAIZ / "scripts"))
    from evaluar_licitaciones import respuesta_antes
    for cierre in ("2026-11-10 15:00:00", "2026-11-03 10:00:00", None, "mal"):
        lic = {"fecha_cierre": cierre}
        assert respuesta_antes(lic, date(2026, 11, 2)) == prov.responder_antes(lic, date(2026, 11, 2))


def test_busqueda_interrumpida_no_se_repite_sola(plataforma, monkeypatch):
    from streamlit.testing.v1 import AppTest

    llamadas = []

    def lenta(lic, items, clave, cfg=None, **k):   # como si el usuario hubiera cortado la corrida
        llamadas.append(clave)
        raise prov.ErrorBusqueda("interrumpida")
    monkeypatch.setattr(prov, "buscar", lenta)
    at = AppTest.from_function(_ficha, args=(str(RAIZ),), default_timeout=60)
    at.secrets["anthropic_api_key"] = "sk-prueba"
    at.run()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert llamadas == ["sk-prueba"]                                  # la segunda corrida no vuelve a pagar
    assert any("no terminó o no resultó" in c.value for c in at.caption)
    assert any(b.label == "Buscar proveedores" for b in at.button)


def test_lista_ignora_proveedores_sin_nombre(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    import sys
    sys.path.insert(0, str(RAIZ / "plataforma"))
    import cotizar

    carpeta = RAIZ / "informes" / "evaluacion" / "proveedores"
    archivo = carpeta / "0-0-PRUEBA.json"
    archivo.write_text(json.dumps([{"nombre": None}, {"nombre": "Con nombre"}]), encoding="utf-8")
    try:
        monkeypatch.setattr(cotizar, "busqueda", lambda codigo: {"proveedores": [{"nombre": None}]})
        nombres = [p.get("nombre") for p in cotizar.lista("0-0-PRUEBA", [])]
    finally:
        archivo.unlink()
    assert nombres == [None, "Con nombre"]


# --- Precios (02-11): alternativas por línea, solo si el precio está escrito en la página -----------

def test_precio_en_la_pagina_con_formato_chileno_y_no_dentro_de_otro_numero():
    assert prov._precio_en(14990, "Precio: $14.990 IVA incluido")
    assert prov._precio_en(14990.0, "$ 14990")
    assert prov._precio_en(14990, "14,990.00")
    assert prov._precio_en(14990, "Oferta $14.990,00")
    assert not prov._precio_en(14990, "$114.990")
    assert not prov._precio_en(14990, "$14.990.000")
    assert not prov._precio_en(4990, "$14.990")


def test_depurar_precios_deja_los_respaldados_en_formato_mercado_del_mas_barato_al_mas_caro():
    texto = "Silla A $59.990 · Silla B $45.000 + IVA · Caja 12 sillas $480.000"
    urls = {"https://a.cl/silla", "https://b.cl/silla"}
    precios = [
        {"linea": 1, "proveedor": "A", "producto": "Silla A", "precio": 59990, "iva_incluido": True, "unidades": 1,
         "coincidencia": "exacta", "url": "https://a.cl/silla", "nota": None},
        {"linea": 1, "proveedor": "B", "producto": "Silla B", "precio": 45000, "iva_incluido": False, "unidades": 1,
         "coincidencia": "equivalente", "url": "https://b.cl/silla", "nota": None},
        {"linea": 1, "proveedor": "C", "producto": "Caja", "precio": 480000, "iva_incluido": True, "unidades": 12,
         "coincidencia": "rara", "url": "https://c.cl/caja", "nota": None},
        {"linea": 1, "proveedor": "Inventado", "producto": "Silla", "precio": 30000, "iva_incluido": True,
         "unidades": 1, "coincidencia": "exacta", "url": "https://d.cl", "nota": None},   # no está en la página
        {"linea": 9, "proveedor": "A", "producto": "Otra", "precio": 59990, "iva_incluido": True, "unidades": 1,
         "coincidencia": "exacta", "url": "https://a.cl/silla", "nota": None},          # línea que no existe
        {"linea": 1, "proveedor": "Sin link", "producto": "Silla", "precio": 45000, "iva_incluido": False,
         "unidades": 1, "coincidencia": "exacta", "url": "a.cl", "nota": None},
        "basura",
    ]
    items = [{"linea": 1, "cantidad": 10}]
    r = prov.depurar_precios(precios, texto, urls, items, "1-1-LE26", "2026-11-02T10:00-03:00")
    assert [m["tienda"] for m in r] == ["C", "B", "A"]
    caja, b, a = r
    assert caja["precio_unitario_neto"] == round(480000 / 1.19 / 12, 2) and caja["coincidencia"] == "aproximada"
    assert not caja["verificado"]                                       # la página no salió en la búsqueda
    assert b["precio_unitario_neto"] == 45000 and b["verificado"]       # «+ IVA»: ya es neto
    assert a["precio_unitario_neto"] == round(59990 / 1.19, 2)
    assert a["codigo"] == "1-1-LE26" and a["fecha_consulta"] == "2026-11-02" and a["origen"] == prov.ORIGEN_PRECIO
    assert [m["clave"] for m in r] == ["1-1-LE26|1|c1", "1-1-LE26|1|c2", "1-1-LE26|1|c3"]


def test_buscar_devuelve_los_precios_respaldados(monkeypatch):
    datos = {"resumen": "ok", "proveedores": [], "precios": [
        {"linea": 1, "proveedor": "Mochilas Chile", "producto": "Mochila 30 L", "precio": 12990,
         "iva_incluido": True, "unidades": 1, "coincidencia": "exacta", "url": "https://www.mochilas.cl/m30",
         "nota": None},
        {"linea": 1, "proveedor": "Otra", "producto": "Mochila", "precio": 9990, "iva_incluido": True, "unidades": 1,
         "coincidencia": "exacta", "url": "https://otra.cl/m", "nota": None}]}
    final = _respuesta([
        _Bloque(type="web_fetch_tool_result", content=_Bloque(
            type="web_fetch_result", url="https://www.mochilas.cl/m30",
            content=_Bloque(type="document", source=_Bloque(type="text", data="Mochila escolar 30 L $12.990")))),
        _Bloque(type="text", text=json.dumps(datos))])
    r = prov.buscar(LIC, ITEMS, "clave", CFG, cliente=_Cliente([final]),
                    ahora=datetime(2026, 11, 2, 10, 0, tzinfo=prov.CHILE))
    assert [m["tienda"] for m in r["precios"]] == ["Mochilas Chile"]      # 9.990 no estaba en ninguna página
    assert r["precios"][0]["verificado"] and r["precios"][0]["precio_unitario_neto"] == round(12990 / 1.19, 2)


PRECIO_SILLA = {"codigo": "1-1-LE26", "linea": 1, "tienda": "Sillas Pro", "producto_mercado": "Silla ergonómica X",
                "url": "https://sillaspro.cl/x", "precio": 35990, "iva_incluido": True, "unidades_equivalentes": 1,
                "precio_unitario_neto": round(35990 / 1.19, 2), "coincidencia": "exacta", "verificado": True,
                "fecha_consulta": "2026-11-02", "nota": None, "origen": prov.ORIGEN_PRECIO,
                "clave": "1-1-LE26|1|c1", "opcion": 1}


def test_ficha_muestra_los_precios_y_la_evaluacion_los_usa(plataforma, monkeypatch):
    from streamlit.testing.v1 import AppTest

    con_precios = ENCONTRADOS | {"precios": [PRECIO_SILLA]}
    monkeypatch.setattr(prov, "buscar", lambda lic, items, clave, cfg=None, **k: con_precios)
    at = AppTest.from_function(_ficha, args=(str(RAIZ),), default_timeout=60)
    at.secrets["anthropic_api_key"] = "sk-prueba"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    tabla = at.dataframe[-1].value
    assert list(tabla["Proveedor"]) == ["Sillas Pro"] and list(tabla["Mejor"]) == [True]
    assert list(tabla["Costo neto línea"]) == [round(35990 / 1.19 * 10)]
    assert any("1 alternativas para 1 de 1 líneas" in m.value for m in at.markdown)

    # Otra página de la misma plataforma (otra sesión): el precio guardado entra a la evaluación.
    import cotizar
    cotizar._memoria().clear()
    cotizar._automaticas().clear()
    monkeypatch.setattr(prov, "leer_precios", lambda **k: {"1-1-LE26": [PRECIO_SILLA]})
    cotizar.comun._indice_precios.clear()
    lista = AppTest.from_function(_lista, args=(str(RAIZ),), default_timeout=60).run()
    assert not lista.exception, [e.value for e in lista.exception]
    decision = lista.dataframe[0].value["Decisión"][0]
    assert decision != "⚪ Falta precio"


def _lista(raiz: str) -> None:
    import sys

    sys.path.insert(0, raiz + "/plataforma")
    import explorar

    explorar.licitaciones()


def test_precio_verificado_solo_si_esta_en_la_pagina_de_ese_producto():
    bloques = [
        _Bloque(type="web_fetch_tool_result", content=_Bloque(
            type="web_fetch_result", url="https://a.cl/silla",
            content=_Bloque(type="document", source=_Bloque(type="text", data="Silla ergonómica $59.990")))),
        _Bloque(type="web_fetch_tool_result", content=_Bloque(
            type="web_fetch_result", url="https://b.cl/silla",
            content=_Bloque(type="document", source=_Bloque(type="text", data="Silla oficina $45.000 + IVA")))),
    ]
    leidas = prov.paginas(bloques)
    assert set(leidas) == {"https://a.cl/silla", "https://b.cl/silla"}
    texto, urls = prov.evidencia(bloques)
    precios = [
        {"linea": 1, "proveedor": "A", "producto": "Silla", "precio": 59990, "iva_incluido": True, "unidades": 1,
         "coincidencia": "exacta", "url": "https://a.cl/silla", "nota": None},
        # 45.000 está escrito, pero en la página de B, no en la de C (que Claude no abrió)
        {"linea": 1, "proveedor": "C", "producto": "Silla", "precio": 45000, "iva_incluido": False, "unidades": 1,
         "coincidencia": "exacta", "url": "https://c.cl/silla", "nota": None},
        # la página de A se abrió, pero este precio no está en ella
        {"linea": 1, "proveedor": "A2", "producto": "Silla", "precio": 45000, "iva_incluido": False, "unidades": 1,
         "coincidencia": "exacta", "url": "https://a.cl/silla", "nota": None},
    ]
    r = {m["tienda"]: m for m in prov.depurar_precios(precios, texto, urls, [{"linea": 1}], "1-1-LE26",
                                                      "2026-11-02T10:00-03:00", leidas)}
    assert r["A"]["verificado"] and not r["C"]["verificado"] and not r["A2"]["verificado"]


def test_pedido_sin_formato_json_tambien_pide_precios():
    assert '"precios"' in prov._SOLO_JSON and '"iva_incluido"' in prov._SOLO_JSON


def test_tope_diario_de_busquedas_automaticas_vale_para_todas_las_sesiones(plataforma, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import cotizar

    llamadas = []
    monkeypatch.setattr(prov, "buscar", lambda lic, items, clave, cfg=None, **k: llamadas.append(clave) or ENCONTRADOS)
    cotizar._automaticas()[cotizar.hoy_chile().isoformat()] = 10      # otras sesiones ya gastaron el tope
    at = AppTest.from_function(_ficha, args=(str(RAIZ),), default_timeout=60)
    at.secrets["anthropic_api_key"] = "sk-prueba"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert llamadas == []
    assert any("búsquedas automáticas de hoy" in c.value for c in at.caption)
    assert any(b.label == "Buscar proveedores" for b in at.button)
