from radar.filtro import FiltroRubros, normalizar

RUBROS = {
    "aseo": {
        "nombre": "Insumos y aseo",
        "palabras_clave": ["guantes", "aseo", "insumos médicos"],
        "excluir": ["servicio de aseo"],
    },
    "bi": {
        "nombre": "Consultoría BI",
        "palabras_clave": ["Power BI", "control de gestión", "consultoría"],
        "excluir": ["consultoría jurídica"],
    },
}


def test_normalizar_quita_tildes_y_mayusculas():
    assert normalizar("  Consultoría   en GESTIÓN ") == "consultoria en gestion"


def test_detecta_rubro_sin_importar_tildes():
    r = FiltroRubros(RUBROS).evaluar("ADQUISICIÓN DE INSUMOS MEDICOS Y GUANTES")
    assert r.rubro == "aseo"
    assert r.palabras == ["guantes", "insumos medicos"]


def test_respeta_bordes_de_palabra():
    assert not FiltroRubros(RUBROS).evaluar("Paseo de fin de año").coincide


def test_exclusion_descarta_el_rubro():
    assert not FiltroRubros(RUBROS).evaluar("Contratación servicio de aseo hospital").coincide


def test_elige_rubro_con_mas_coincidencias():
    r = FiltroRubros(RUBROS).evaluar("Consultoría control de gestión y dashboard Power BI; guantes")
    assert r.rubro == "bi"
    assert r.rubros == ["bi", "aseo"]
