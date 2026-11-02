import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _lic(codigo, cierre, **cambios):
    return {"codigo": codigo, "nombre": "Sillas", "rubro": "mobiliario", "tipo": "LE", "region": "Región del Maule",
            "fecha_cierre": cierre, "dias_restantes": 9, "monto_estimado": 1_000_000, "moneda": "CLP"} | cambios


def _item(codigo):
    return {"codigo": codigo, "linea": 1, "producto": "Silla", "descripcion": "Silla de visita apilable negra",
            "cantidad": 10, "unidad": "Unidad"}


def _elegir(tmp_path, monkeypatch, lics, *opciones):
    import seleccionar_mercado as script
    (tmp_path / "items.json").write_text(json.dumps([_item(l["codigo"]) for l in lics]))
    (tmp_path / "lics.json").write_text(json.dumps(lics))
    (tmp_path / "mercado").mkdir(exist_ok=True)
    monkeypatch.setattr(script, "hoy_chile", lambda: date(2026, 10, 24))
    monkeypatch.setattr(sys, "argv", ["x", "--items", str(tmp_path / "items.json"), "--licitaciones",
                                      str(tmp_path / "lics.json"), "--salida", str(tmp_path / "lote.json"),
                                      "--mercado", str(tmp_path / "mercado"), *opciones])
    script.main()
    return [e["codigo"] for e in json.loads((tmp_path / "lote.json").read_text())]


def test_compras_agiles_de_un_dia_entran_en_sus_cupos(tmp_path, monkeypatch):
    lics = [_lic("1-1-LE26", "2026-10-30 15:00:00"), _lic("2-2-LE26", "2026-10-31 15:00:00"),
            # Compras Ágiles: cierran mañana (se publicaron con dias_restantes viejo)
            _lic("3-3-COT26", "2026-10-25 15:00:00", tipo="Compra Ágil", dias_restantes=2),
            _lic("4-4-COT26", "2026-10-25 15:00:00", tipo="Compra Ágil", dias_restantes=2)]
    elegidas = _elegir(tmp_path, monkeypatch, lics, "--maximo", "4", "--por-rubro", "2", "--compras-agiles", "2")
    # Las dos Compras Ágiles van primero y no le quitan el cupo del rubro a las licitaciones.
    assert elegidas == ["3-3-COT26", "4-4-COT26", "1-1-LE26", "2-2-LE26"]


def test_licitacion_que_cierra_pronto_o_cerrada_no_entra(tmp_path, monkeypatch):
    lics = [_lic("1-1-LE26", "2026-10-26 15:00:00", dias_restantes=5),     # 2 días: poco para cotizar
            _lic("2-2-COT26", "2026-10-24 15:00:00", tipo="Compra Ágil"),   # cierra hoy
            _lic("3-3-LE26", "2026-10-28 15:00:00")]
    assert _elegir(tmp_path, monkeypatch, lics, "--compras-agiles", "1") == ["3-3-LE26"]


def test_sin_emt_salta_las_compras_agiles_de_primer_llamado(tmp_path, monkeypatch):
    import seleccionar_mercado as script
    lics = [_lic("1-1-COT26", "2026-10-25 15:00:00", tipo="Compra Ágil", llamado=1),
            _lic("2-2-COT26", "2026-10-25 15:00:00", tipo="Compra Ágil", llamado=2),
            _lic("3-3-LE26", "2026-10-30 15:00:00")]
    monkeypatch.setattr(script, "cargar_config", lambda: {"compra_agil": {"soy_emt": False}})
    assert _elegir(tmp_path, monkeypatch, lics, "--compras-agiles", "2") == ["2-2-COT26", "3-3-LE26"]
    monkeypatch.setattr(script, "cargar_config", lambda: {"compra_agil": {"soy_emt": True}})
    assert _elegir(tmp_path, monkeypatch, lics, "--compras-agiles", "2") == ["1-1-COT26", "2-2-COT26", "3-3-LE26"]


def _mercado(tmp_path, codigo, precios: dict):
    """informes/mercado/<codigo>.json con un precio por línea (None = línea buscada sin precio)."""
    items = [{"linea": linea, "opciones": [] if precio is None else [
        {"url": f"https://t.cl/{linea}", "precio": precio, "precio_unitario_neto": precio, "coincidencia": "exacta"}]}
        for linea, precio in precios.items()]
    (tmp_path / "mercado").mkdir(exist_ok=True)
    (tmp_path / "mercado" / f"{codigo}.json").write_text(json.dumps({"codigo": codigo, "items": items}))


def test_las_que_quedaron_a_medias_vuelven_primero_solo_con_las_lineas_que_faltan(tmp_path, monkeypatch):
    import seleccionar_mercado as script
    lics = [_lic("1-1-LE26", "2026-10-30 15:00:00"),                                   # nueva
            _lic("2-2-LE26", "2026-10-30 15:00:00", monto_estimado=10_000_000),         # a medias
            _lic("3-3-LE26", "2026-10-30 15:00:00"),                                   # completa
            _lic("4-4-LE26", "2026-10-30 15:00:00"),                                   # buscada sin resultado
            _lic("5-5-LE26", "2026-10-30 15:00:00", monto_estimado=100)]               # NO GO por monto
    dos_lineas = [_item(l["codigo"]) | {"linea": n} for l in lics for n in (1, 2)]
    _mercado(tmp_path, "2-2-LE26", {1: 5000, 2: None})
    _mercado(tmp_path, "3-3-LE26", {1: 5000, 2: 5000})
    _mercado(tmp_path, "4-4-LE26", {1: None, 2: None})
    _mercado(tmp_path, "5-5-LE26", {1: 5000, 2: None})
    (tmp_path / "items.json").write_text(json.dumps(dos_lineas))
    (tmp_path / "lics.json").write_text(json.dumps(lics))
    monkeypatch.setattr(script, "hoy_chile", lambda: date(2026, 10, 24))
    monkeypatch.setattr(sys, "argv", ["x", "--items", str(tmp_path / "items.json"), "--licitaciones",
                                      str(tmp_path / "lics.json"), "--salida", str(tmp_path / "lote.json"),
                                      "--mercado", str(tmp_path / "mercado"), "--maximo", "5", "--por-rubro", "5"])
    script.main()
    lote = json.loads((tmp_path / "lote.json").read_text())
    assert [e["codigo"] for e in lote] == ["2-2-LE26", "1-1-LE26"]
    assert lote[0]["completar"] and [i["linea"] for i in lote[0]["items"]] == [2]
    assert "completar" not in lote[1] and len(lote[1]["items"]) == 2


def test_guardar_mercado_combina_con_lo_que_habia(tmp_path):
    import guardar_mercado
    destino = tmp_path / "1-1-LE26.json"
    destino.write_text(json.dumps({"codigo": "1-1-LE26", "nombre": "Sillas", "items": [
        {"linea": 1, "opciones": [{"url": "https://a.cl/1", "precio_unitario_neto": 100}]},
        {"linea": 2, "opciones": [{"url": "https://a.cl/2", "precio_unitario_neto": 300}]}]}))
    nueva = {"codigo": "1-1-LE26", "fecha_consulta": "2026-11-03", "items": [
        {"linea": 2, "opciones": [{"url": "https://b.cl/2", "precio_unitario_neto": 200},
                                  {"url": "https://a.cl/2", "precio_unitario_neto": 250}]},
        {"linea": 3, "opciones": [{"url": "https://b.cl/3", "precio_unitario_neto": 50}]}]}
    r = guardar_mercado.combinar(destino, nueva)
    assert [i["linea"] for i in r["items"]] == [1, 2, 3]
    assert r["items"][0]["opciones"][0]["url"] == "https://a.cl/1"                     # línea 1 se conserva
    assert [o["url"] for o in r["items"][1]["opciones"]] == ["https://b.cl/2", "https://a.cl/2"]   # sin repetir
    assert r["nombre"] == "Sillas" and r["fecha_consulta"] == "2026-11-03"
    assert guardar_mercado.combinar(tmp_path / "no-existe.json", nueva) == nueva
