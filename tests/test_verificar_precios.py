import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verificar_precios import comparar, precios_en_pagina, verificar_opcion  # noqa: E402

PAGINA = """<html><head><meta property="product:price:amount" content="3350">
<script type="application/ld+json">{"@type":"Product","offers":{"price":"3350.00","priceCurrency":"CLP"}}</script>
</head><body><span>Antes $ 4.190</span><span class="precio">$3.350</span> Envío desde $2.990</body></html>"""


def test_precios_en_pagina_lee_json_ld_meta_y_texto():
    precios = precios_en_pagina(PAGINA)
    assert precios[0] == 3350
    assert 4190 in precios and 2990 in precios


def test_comparar_tolerancia():
    assert comparar(3350, [4190, 3350]) == (True, 3350)
    assert comparar(3350, [3400]) == (True, 3400)        # 1,5 %
    assert comparar(3350, [3990]) == (False, 3990)
    assert comparar(3350, []) == (False, None)


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class _Sesion:
    def __init__(self, resp):
        self.resp = resp

    def get(self, url, **kw):
        return self.resp


def test_verificar_opcion_marca_y_explica():
    op = {"url": "https://tienda.cl/x", "precio": 3350, "verificado": False}
    verificar_opcion(op, _Sesion(_Resp(200, PAGINA)), "2026-10-18")
    assert op["verificado"] is True and op["precio_pagina"] == 3350
    op = {"url": "https://tienda.cl/x", "precio": 5000, "verificado": False}
    verificar_opcion(op, _Sesion(_Resp(200, PAGINA)), "2026-10-18")
    assert op["verificado"] is False and "puede haber cambiado" in op["verificacion_pagina"]
    op = {"url": "https://tienda.cl/x", "precio": 5000}
    verificar_opcion(op, _Sesion(_Resp(403)), "2026-10-18")
    assert "HTTP 403" in op["verificacion_pagina"]
    op = {"url": "https://tienda.cl/x", "precio": 5000}
    verificar_opcion(op, _Sesion(_Resp(200, "<html>sin precio</html>")), "2026-10-18")
    assert "JavaScript" in op["verificacion_pagina"]


def test_mensaje_precio_distinto_conserva_la_coma():
    op = {"url": "https://tienda.cl/x", "precio": 119900}
    verificar_opcion(op, _Sesion(_Resp(200, "<span>$129.900</span>")), "2026-10-18")
    assert "$129.900, no $119.900" in op["verificacion_pagina"]
