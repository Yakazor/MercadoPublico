import pandas as pd

from radar.ordenes_compra import resumen_precios


def test_resumen_precios_agrupa_por_producto_normalizado():
    items = pd.DataFrame([
        {"rubro_nombre": "Aseo", "producto": "Guantes Nitrilo", "unidad": "Caja", "moneda": "CLP",
         "codigo_oc": "1", "proveedor": "A", "cantidad": 10, "precio_unitario_neto": 100, "total_item": 1000},
        {"rubro_nombre": "Aseo", "producto": "guantes nitrilo", "unidad": "Caja", "moneda": "CLP",
         "codigo_oc": "2", "proveedor": "B", "cantidad": 5, "precio_unitario_neto": 300, "total_item": 1500},
        {"rubro_nombre": "Aseo", "producto": "Cloro", "unidad": "Litro", "moneda": "CLP",
         "codigo_oc": "2", "proveedor": "B", "cantidad": 1, "precio_unitario_neto": 0, "total_item": 0},
    ])
    r = resumen_precios(items)
    assert len(r) == 1
    fila = r.iloc[0]
    assert fila["n_ordenes"] == 2 and fila["precio_mediana"] == 200 and fila["cantidad_total"] == 15
