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
