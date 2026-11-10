import json
from datetime import date
import sys
from pathlib import Path

from openpyxl import load_workbook
import pytest

from radar.evaluacion import CONDICIONADO, FALTA_PRECIO, GO, NO_GO, evaluar, puntaje, zona_logistica
from radar.presupuesto import armar_presupuesto

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _lic(**cambios):
    lic = {"codigo": "1-1-LE26", "nombre": "Sillas", "organismo": "Muni", "region": "Región Metropolitana de Santiago",
           "monto_estimado": 2_000_000, "moneda": "CLP", "tipo": "LE", "dias_restantes": 6,
           "fecha_cierre": "2026-10-30 15:00:00", "rubro_nombre": "Mobiliario"}
    return lic | cambios


def _presupuesto(precio=10_000, coincidencia="exacta", cantidad=100, unidad="Unidad", lineas=1, con_precio=None):
    items = [{"codigo": "1-1-LE26", "linea": n, "producto": "Silla", "cantidad": cantidad, "unidad": unidad}
             for n in range(1, lineas + 1)]
    con_precio = lineas if con_precio is None else con_precio
    mercado = [{"linea": n, "precio_unitario_neto": precio, "coincidencia": coincidencia, "verificado": True,
                "tienda": "Tienda"} for n in range(1, con_precio + 1)]
    return armar_presupuesto(items, mercado)


def test_go_con_precios_exactos_margen_y_tiempo():
    ev = evaluar(_lic(), _presupuesto())
    assert ev.decision == GO
    assert ev.costos["directos"] == 1_000_000
    assert ev.margenes["bruto"] > ev.margenes["neto"] > 0
    assert ev.margenes["equilibrio_neto"] == ev.costos["total"]
    assert ev.riesgo == "Bajo" and ev.factibilidad["financiera"] == "Alta"


def test_aproximados_y_precios_faltantes_condicionan():
    ev = evaluar(_lic(), _presupuesto(coincidencia="aproximada"))
    assert ev.decision == CONDICIONADO
    assert any("aproximados" in c for c in ev.condiciones)
    ev = evaluar(_lic(monto_estimado=10_000_000), _presupuesto(lineas=5, con_precio=4))
    assert ev.decision == CONDICIONADO and ev.cobertura == 0.8
    assert any("faltan" in c for c in ev.condiciones)


def test_con_precio_para_menos_del_80_por_ciento_de_las_lineas_falta_precio():
    # Con la mitad de las líneas el margen sale de medio pedido: ni GO ni NO GO por margen.
    ev = evaluar(_lic(monto_estimado=8_000_000), _presupuesto(lineas=4, con_precio=2))
    assert ev.decision == FALTA_PRECIO and ev.cobertura == 0.5
    assert "2 líneas que faltan" in ev.condiciones[0] and "50%" in ev.razones[0]
    assert puntaje(evaluar(_lic(), _presupuesto())) > puntaje(ev)
    # La regla de monto manda: sobre el monto es NO GO aunque falten precios.
    assert evaluar(_lic(monto_estimado=100_000), _presupuesto(lineas=4, con_precio=2)).decision == NO_GO
    assert evaluar(_lic(), _presupuesto(lineas=4, con_precio=2), {"cobertura_minima": 0.5}).decision != FALTA_PRECIO


def _con_referencia(ref, lineas=2, con_ref=2, ordenes=12, p25=None, p75=None, cantidad=100):
    """Líneas a $10.000 neto de tienda; las primeras `con_ref` con referencia OC (precisa por defecto:
    12 órdenes y p25–p75 a ±10 % de la mediana)."""
    items = [{"codigo": "1-1-LE26", "linea": n, "producto": "Silla", "cantidad": cantidad, "unidad": "Unidad",
              **({"ref_mediana": ref, "ref_n_ordenes": ordenes, "ref_p25": p25 or ref * 0.9, "ref_p75": p75 or ref * 1.1}
                 if n <= con_ref else {"ref_mediana": None})} for n in range(1, lineas + 1)]
    mercado = [{"linea": n, "precio_unitario_neto": 10_000, "coincidencia": "exacta", "verificado": True,
                "tienda": "Tienda"} for n in range(1, lineas + 1)]
    return armar_presupuesto(items, mercado, iva_es_costo=True)


def test_sin_monto_estimado_el_techo_son_las_oc_del_estado():
    sin_monto = _lic(monto_estimado=None)
    p = _con_referencia(10_000)                 # el Estado pagó 10.000; la oferta sale ~15.000 por unidad
    ev = evaluar(sin_monto, p)
    assert ev.decision == NO_GO
    assert any("órdenes de compra parecidas" in r for r in ev.razones)
    assert any("supera en" in r for r in ev.riesgos)
    # Bajo el techo (pagó 14.000 → techo 16.800): sigue evaluándose por margen.
    assert evaluar(sin_monto, _con_referencia(14_000)).decision != NO_GO
    # Con referencia en pocas líneas (1 de 3) no hay techo.
    ev = evaluar(sin_monto, _con_referencia(10_000, lineas=3, con_ref=1))
    assert ev.decision != NO_GO and any("no hay una referencia precisa" in r for r in ev.riesgos)
    # Con monto publicado manda el monto, no las OC.
    assert evaluar(_lic(monto_estimado=10_000_000), p).decision != NO_GO


def test_una_mediana_de_categoria_amplia_o_de_pocas_oc_no_es_techo():
    # Auditoría del 10-11: «Vestuario» (179 OC, p25 $7.200, mediana $12.900, p75 $30.000) marcaba NO GO una
    # parka de pluma, y «Pesas» (2 OC) una mancuerna de 30 kg. Esas referencias no son un techo de precio.
    sin_monto = _lic(monto_estimado=None)
    dispersa = evaluar(sin_monto, _con_referencia(10_000, p25=5_600, p75=23_000))
    pocas = evaluar(sin_monto, _con_referencia(10_000, ordenes=2))
    for ev in (dispersa, pocas):
        assert ev.decision == CONDICIONADO                           # ya no es NO GO…
        assert any("revisar en las bases el presupuesto" in c for c in ev.condiciones)   # …pero tampoco GO a ciegas
        assert not any("supera en" in r for r in ev.riesgos)
    p = _con_referencia(10_000, p25=5_600, p75=23_000)
    assert p["referencia_oc_neta"] and p["referencia_confiable_neta"] is None
    assert [i["referencia_confiable"] for i in p["items"]] == [False, False]
    # Datos publicados antes de ref_p75: se usa mediana / p25.
    from radar.presupuesto import referencia_confiable
    assert referencia_confiable({"ref_mediana": 100, "ref_p25": 90, "ref_n_ordenes": 8})
    assert not referencia_confiable({"ref_mediana": 12_900, "ref_p25": 7_200, "ref_n_ordenes": 179})
    assert not referencia_confiable({"ref_mediana": 100, "ref_p25": 90, "ref_n_ordenes": 4})
    assert not referencia_confiable({"ref_mediana": 100})


def test_sin_monto_la_oferta_no_puede_pasar_el_tope_del_tipo_de_licitacion():
    # LE: menos de 1.000 UTM ($72.151.000). 2 líneas × 2.600 u × ~$15.000 neto = ~$78 M neto.
    grande = _con_referencia(None, con_ref=0, cantidad=2_600)
    ev = evaluar(_lic(monto_estimado=None, tipo="LE"), grande)
    assert ev.decision == NO_GO
    assert "Sin monto estimado, la oferta supera el tope del tipo de licitación (LE: hasta 1.000 UTM)." in ev.razones
    assert any(r.endswith("(LE: hasta 1.000 UTM, $72.151.000).") for r in ev.riesgos)
    assert ev.supuestos["con_garantia"]                               # sin monto, la garantía sale de la oferta
    # El mismo pedido en una LP (hasta 2.000 UTM) o LR (sin tope) no choca con el tope.
    for tipo in ("LP", "LR"):
        assert not any("tope" in r for r in evaluar(_lic(monto_estimado=None, tipo=tipo), grande).razones)
    # Con monto publicado manda el monto.
    assert not any("tope" in r for r in evaluar(_lic(monto_estimado=200_000_000, tipo="LE"), grande).razones)
    chica = evaluar(_lic(monto_estimado=None, tipo="L1"), _con_referencia(None, con_ref=0))
    assert not chica.supuestos["con_garantia"] and any("admite hasta 100 UTM" in r for r in chica.riesgos)


def test_sobre_el_monto_dice_cuanto_mas_barato_hay_que_comprar():
    ev = evaluar(_lic(monto_estimado=1_000_000), _presupuesto())      # oferta $1.499.400
    assert ev.decision == NO_GO and any("un 33% más barato" in r for r in ev.riesgos)
    parcial = evaluar(_lic(monto_estimado=1_000_000), _presupuesto(lineas=2, con_precio=1))
    assert any("al menos un 33% más barato" in r for r in parcial.riesgos)


def test_no_go_por_cierre_monto_o_sin_precios():
    assert evaluar(_lic(dias_restantes=0), _presupuesto()).decision == NO_GO
    assert evaluar(_lic(monto_estimado=500_000), _presupuesto()).decision == NO_GO     # oferta muy sobre el monto
    assert evaluar(_lic(), _presupuesto(con_precio=0)).decision == NO_GO
    assert evaluar(_lic(solo_regulados=1), _presupuesto()).decision == NO_GO


def test_costos_de_region_garantia_y_orden():
    cerca = evaluar(_lic(), _presupuesto())
    lejos = evaluar(_lic(region="Región de Magallanes y de la Antártica Chilena"), _presupuesto())
    assert lejos.costos["logistica"] == 4 * cerca.costos["logistica"]
    assert zona_logistica("Región de Ñuble") == "lejana" and zona_logistica(None) == "media"
    grande = evaluar(_lic(monto_estimado=100_000_000), _presupuesto())
    assert grande.costos["garantia"] > 0 and cerca.costos["garantia"] == 0
    assert puntaje(cerca) > puntaje(evaluar(_lic(), _presupuesto(coincidencia="aproximada")))


def test_script_genera_excel_informes_correos_y_log(tmp_path, monkeypatch):
    import evaluar_licitaciones as script

    lics = [_lic(), _lic(codigo="2-2-COT26", tipo="Compra Ágil", plazo_entrega_dias=3, llamado=1, nombre="= a lo solicitado"),
            _lic(codigo="3-3-LE26", dias_restantes=2, fecha_cierre="2026-10-22 15:00:00")]   # ya cerró
    items = [{"codigo": "1-1-LE26", "linea": 1, "producto": "Silla", "descripcion": "Silla de oficina",
              "cantidad": 100, "unidad": "Unidad"}]
    mercado = tmp_path / "mercado"
    mercado.mkdir()
    (mercado / "1-1-LE26.json").write_text(json.dumps({"codigo": "1-1-LE26", "items": [{"linea": 1, "opciones": [
        {"tienda": "Tienda X", "url": "https://x.cl/silla", "precio": 11_900, "iva_incluido": True,
         "unidades_equivalentes": 1, "precio_unitario_neto": 10_000, "coincidencia": "exacta", "verificado": True}]}]}))
    (tmp_path / "items.json").write_text(json.dumps(items))
    (tmp_path / "lics.json").write_text(json.dumps(lics))
    entrada = tmp_path / "entrada.json"
    entrada.write_text(json.dumps({"licitaciones_procesadas": "1-1-LE26", "resultado": "revisada"}))
    salida = tmp_path / "eval"
    # Los días al cierre se cuentan desde hoy (no se usa el dias_restantes publicado).
    monkeypatch.setattr(script, "hoy_chile", lambda: date(2026, 10, 24))
    monkeypatch.setattr(sys, "argv", ["x", "--items", str(tmp_path / "items.json"), "--licitaciones",
                                      str(tmp_path / "lics.json"), "--mercado", str(mercado), "--salida", str(salida),
                                      "--registrar", str(entrada)])
    script.main()

    wb = load_workbook(salida / "Licitaciones_evaluadas.xlsx")
    assert wb.sheetnames == ["Licitaciones", "Evaluación", "Claude Log"]
    codigos = [r[0].value for r in wb["Licitaciones"].iter_rows(min_row=2)]
    assert sorted(codigos) == ["1-1-LE26", "2-2-COT26"]           # la cerrada no entra
    # Un nombre que empieza con «=» queda como texto, no como fórmula.
    igual = [c for f in wb["Licitaciones"].iter_rows() for c in f if c.value == "= a lo solicitado"]
    assert igual and all(c.data_type == "s" for c in igual)
    assert wb["Evaluación"]["C2"].value == GO
    assert [r[1].value for r in wb["Claude Log"].iter_rows(min_row=2)] == ["Claude", "Sistema (script)"]
    correo = (salida / "licitaciones" / "1-1-LE26_correos.md").read_text()
    assert "Asunto:** Solicitud de cotización – Sillas" in correo and "Tienda X" in correo and "- Valor neto." in correo
    assert "🟢 GO" in (salida / "licitaciones" / "1-1-LE26_go_no_go.md").read_text()
    assert "Punto de equilibrio" in (salida / "licitaciones" / "1-1-LE26_informe.md").read_text()
    # Segunda corrida el mismo día: reemplaza la entrada automática y conserva la de Claude.
    monkeypatch.setattr(sys, "argv", sys.argv[:-2])
    script.main()
    log = json.loads((salida / "claude_log.json").read_text())
    assert [x["autor"] for x in log] == ["Claude", "Sistema (script)"]


def test_oferta_sobre_el_monto_es_no_go_y_el_iva_sin_credito_es_costo():
    # Oferta 1.000.000 × 1,05 × 1,2 × 1,19 = 1.499.400 con IVA: un poco sobre 1.400.000 ya es NO GO.
    ev = evaluar(_lic(monto_estimado=1_400_000), _presupuesto())
    assert ev.decision == NO_GO and any("supera el monto" in r for r in ev.razones)
    assert evaluar(_lic(monto_estimado=1_600_000), _presupuesto()).decision != NO_GO
    # Sin crédito fiscal el IVA de la compra suma al costo (no a la mercadería) y baja el margen.
    sin_credito = armar_presupuesto([{"linea": 1, "producto": "Silla", "cantidad": 100, "unidad": "Unidad"}],
                                    [{"linea": 1, "precio_unitario_neto": 10_000, "coincidencia": "exacta",
                                      "verificado": True, "tienda": "Tienda"}], iva_es_costo=True)
    ev = evaluar(_lic(monto_estimado=5_000_000), sin_credito)
    assert sin_credito["iva_compras"] == pytest.approx(190_000) and ev.costos["iva_compras"] == pytest.approx(190_000)
    assert ev.costos["directos"] == pytest.approx(1_000_000)
    assert ev.costos["total"] == pytest.approx(ev.costos["directos"] + ev.costos["iva_compras"] + ev.costos["indirectos"])
    assert sin_credito["oferta_neta"] == pytest.approx(1_000_000 * 1.19 * 1.05 * 1.2)
