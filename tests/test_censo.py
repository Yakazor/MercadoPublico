from radar.censo import agregar_censo, muestra_estable
from radar.filtro import FiltroRubros

FILTRO = FiltroRubros({
    "aseo": {"nombre": "Aseo", "palabras_clave": ["papel higienico", "detergentes"]},
})


def _lic(codigo, nombre, items, monto=1000):
    return {"CodigoExterno": codigo, "Nombre": nombre, "Tipo": "LE", "MontoEstimado": monto, "Moneda": "CLP",
            "Items": {"Listado": items}}


def test_muestra_estable_no_depende_del_orden():
    codigos = [f"{i}-1-LE26" for i in range(50)]
    assert muestra_estable(codigos, 10) == muestra_estable(list(reversed(codigos)), 10)
    assert len(set(muestra_estable(codigos, 10))) == 10


def test_agregar_censo_por_segmento_con_cobertura_del_radar():
    detalles = [
        _lic("A", "Compra de papel higiénico", [
            {"CodigoCategoria": "53131600", "Categoria": "Ropa, maletas y productos de aseo personal / Artículos de tocador / Papel higiénico"},
        ], monto=1000),
        _lic("B", "Construcción de sede social", [
            {"CodigoCategoria": "72101500", "Categoria": "Servicios de edificación / Construcción / Obras"},
            {"CodigoCategoria": "53131600", "Categoria": "Ropa, maletas y productos de aseo personal / Artículos de tocador / Jabón"},
        ], monto=2000),
        _lic("C", "Mantención de ascensores", [
            {"CodigoCategoria": "72101500", "Categoria": "Servicios de edificación / Mantención / Ascensores"},
        ], monto=None),
    ]
    censo = agregar_censo(detalles, FILTRO, activas_total=30)
    assert censo["procesadas"] == 3 and censo["detectadas_por_el_radar"] == 1
    por_codigo = {s["codigo"]: s for s in censo["segmentos"]}
    aseo, obras = por_codigo["53"], por_codigo["72"]
    assert aseo["licitaciones"] == 2 and obras["licitaciones"] == 2
    # Muestra de 3 sobre 30 activas: cada licitación representa 10.
    assert aseo["estimado_activas"] == 20
    # El monto de B se reparte entre sus dos segmentos.
    assert aseo["monto_clp_muestra"] == 1000 + 1000
    assert obras["monto_clp_muestra"] == 1000
    assert aseo["detectadas"] == 1 and aseo["rubros"] == {"aseo": 1} and obras["detectadas"] == 0
    assert {f["familia"] for f in obras["familias"]} == {"Construcción", "Mantención"}
