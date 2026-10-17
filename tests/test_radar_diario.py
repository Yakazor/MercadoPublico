import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from radar_diario import listado_completo  # noqa: E402


def test_listado_vacio_no_depura():
    assert not listado_completo(set(), pd.DataFrame({"codigo": ["a"]}))


def test_listado_recortado_no_depura():
    vigentes = pd.DataFrame({"codigo": list("abcdefghij")})
    assert not listado_completo({"a", "b"}, vigentes)
    assert listado_completo(set("abcdefghi"), vigentes)
    assert listado_completo({"x"}, pd.DataFrame(columns=["codigo"]))
