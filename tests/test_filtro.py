import pytest

from radar.config import cargar_config
from radar.filtro import FiltroRubros, normalizar

RUBROS = {
    "aseo": {
        "nombre": "Insumos y aseo",
        "palabras_clave": ["guantes", "articulos de aseo", "insumos médicos"],
        "excluir_en_nombre": ["servicio de aseo"],
    },
    "bi": {
        "nombre": "Consultoría BI",
        "palabras_clave": ["Power BI", "control de gestión", "consultoría en gestión"],
        "excluir_en_nombre": ["consultoría jurídica"],
    },
}


@pytest.fixture(scope="module")
def real():
    return FiltroRubros.desde_config(cargar_config())


def test_normalizar_quita_tildes_y_mayusculas():
    assert normalizar("  Consultoría   en GESTIÓN ") == "consultoria en gestion"


def test_detecta_rubro_sin_importar_tildes():
    r = FiltroRubros(RUBROS).evaluar(nombre="ADQUISICIÓN DE INSUMOS MEDICOS Y GUANTES")
    assert r.rubro == "aseo"
    assert r.palabras == ["guantes", "insumos medicos"]


def test_respeta_bordes_de_palabra():
    assert not FiltroRubros(RUBROS).evaluar(nombre="Paseo de fin de año").coincide


def test_exclusion_en_nombre_descarta_el_rubro():
    assert not FiltroRubros(RUBROS).evaluar(nombre="Contratación servicio de aseo hospital").coincide


def test_elige_rubro_con_mas_coincidencias():
    r = FiltroRubros(RUBROS).evaluar(nombre="Consultoría en gestión: control de gestión y Power BI; guantes")
    assert r.rubro == "bi"
    assert r.rubros == ["bi", "aseo"]


def test_descripcion_sola_no_basta_pero_suma_palabras():
    f = FiltroRubros(RUBROS)
    # La descripción menciona "control de gestión" (p. ej. la unidad solicitante): no basta.
    assert not f.evaluar("Solicitado por el Depto. de Control de Gestión", nombre="Compra de sillas").coincide
    # Con una palabra clave en los ítems, cuenta, y la descripción suma palabras.
    r = f.evaluar("tablero en Power BI", nombre="Servicio de consultoría", items=["Consultoría en gestión"])
    assert r.rubro == "bi" and r.palabras == ["consultoria en gestion", "power bi"]


def test_exclusion_en_nombre_no_afecta_descripcion():
    f = FiltroRubros(RUBROS)
    assert f.evaluar("para uso del servicio de aseo del hospital",
                     nombre="Compra de artículos de aseo").coincide
    assert not f.evaluar("incluye artículos de aseo", nombre="Servicio de aseo oficinas",
                         items=["Artículos de aseo"]).coincide


def test_exclusion_salvo_clave():
    rubros = {"aseo": {"nombre": "Aseo", "palabras_clave": ["guantes", "gasas"],
                       "palabras_candidatas": ["insumos clinicos"],
                       "excluir_en_nombre_salvo_clave": ["sondas"]}}
    f = FiltroRubros(rubros)
    assert not f.es_candidata("Compra de sondas e insumos clínicos")
    assert f.es_candidata("Gasas, guantes y sondas")
    assert f.evaluar(nombre="Gasas, guantes y sondas").coincide


def test_palabras_candidatas_solo_habilitan_el_detalle():
    rubros = {"insumos": {"nombre": "Insumos", "palabras_clave": ["guantes"],
                          "palabras_candidatas": ["insumos clinicos"],
                          "excluir_en_nombre_salvo_clave": ["cateter"]}}
    f = FiltroRubros(rubros)
    nombre = "Insumos clínicos para central de esterilización"
    assert f.es_candidata(nombre)
    assert not f.evaluar(nombre=nombre, items=["cajas plásticas"]).coincide
    assert f.evaluar(nombre=nombre, items=["guantes de nitrilo talla M"]).rubro == "insumos"
    assert not f.es_candidata("Adquisición de catéter e insumos clínicos")
    assert not f.es_candidata("")


def test_formato_antiguo_excluir_se_trata_como_exclusion_en_nombre():
    f = FiltroRubros({"x": {"nombre": "X", "palabras_clave": ["guantes"], "excluir": ["tacticos"]}})
    assert not f.es_candidata("Guantes tácticos")
    # Ya no se aplica a la descripción (antes un "Medicamentos…" en la categoría lo anulaba).
    assert f.evaluar("categoría: guantes tácticos", nombre="Guantes de nitrilo").coincide


# --- Configuración real: casos de la primera corrida y de la revisión ----------

def test_real_casos_del_primer_radar(real):
    assert real.evaluar(nombre="Licencias MicroStrategy y Servicios BI").rubro == "consultoria_gestion_bi"
    assert real.evaluar(nombre="SUMINISTRO ALCOHOL GEL 70% CO DISPENSADOR").rubro == "insumos_medicos_aseo"
    assert not real.evaluar(nombre="SERVICIOS DE ASEO PARA SLEP PUNILLA CORDIILLERA").coincide
    assert not real.evaluar(nombre="ASESORIA A LA INSPECCION FISCAL, RUTA 23-CH").coincide
    assert not real.evaluar(nombre="EPP Depto. Aseo y Ornato").coincide
    assert not real.evaluar(nombre="ADQUISICIÓN DE GUANTES TÁCTICOS MOTORISTA").coincide


def test_real_dispositivos_regulados_y_mixtos(real):
    assert not real.es_candidata("ADQUISICION DE CATETER SONDAS CANULAS TQQ TUBO ENDOTQQ")
    assert not real.es_candidata("ADQ. DE SUTURAS QUIRÚRGICAS E INSUMOS CLÍNICOS")
    assert not real.es_candidata("CONVENIO SUMINISTRO INSUMOS CLINICOS ACCESOS VENOSOS ARTERIALES")
    assert not real.es_candidata("TUBOS ENDOTRAQUEALES E INSUMOS CLINICOS")
    assert not real.es_candidata("Parche DEA adulto e insumos clínicos")
    for mixto in ("CONVENIO DE SUMINISTRO DE GASAS GUANTES JERINGAS MASCARILLAS SUTURAS Y OTROS",
                  "CONVENIO DE SUMINISTRO DE GASAS GUANTES JERINGAS MASCARILLAS SONDAS Y OTROS",
                  "Insumos odontológicos: guantes, mascarillas, eyectores e implantes",
                  "ADQUISICION DE GUANTES DE PROCEDIMIENTO PARA UNIDAD DE DIALISIS",
                  "Artículos de aseo para Unidad de Hemodinamia"):
        assert real.es_candidata(mixto) and real.evaluar(nombre=mixto).coincide, mixto


def test_real_consultoria_requiere_gestion_bi(real):
    assert real.es_candidata("Servicio de consultoría")
    assert not real.evaluar("diagnóstico organizacional", nombre="Servicio de consultoría").coincide
    # Una unidad mencionada en la descripción no convierte cualquier asesoría en BI.
    assert not real.evaluar(
        "Requerido por el Departamento de Planificación Estratégica y Control de Gestión",
        nombre="Consultoría para estudio hidrogeológico sector norte",
    ).coincide
    assert real.evaluar(nombre="Servicio de consultoría",
                        items=["Implementar tablero de control con indicadores de gestión"]
                        ).rubro == "consultoria_gestion_bi"
    assert not real.es_candidata("Consultoría de diseño de arquitectura")
    assert not real.es_candidata("ASESORIA JURIDICA REGULARIZACIÓN DE COMUNIDADES")


@pytest.mark.parametrize("nombre", [
    "Asesoría en arquitectura de datos e implementación de Power BI",
    "Consultoría para diseño de arquitectura de datos y tablero de control de gestión",
    "Implementación de dashboards Power BI para Dirección de Obras Portuarias",
    "Consultoría en control de gestión para la Dirección de Obras Municipales",
    "Definicion de KPIs institucionales",
])
def test_real_bi_no_se_pierde_por_obras_o_arquitectura(real, nombre):
    assert real.es_candidata(nombre)
    assert real.evaluar(nombre=nombre).rubro == "consultoria_gestion_bi"


@pytest.mark.parametrize("nombre", [
    "ADQUISICION DE BOLSAS DE BASURA PARA RESIDUOS DOMICILIARIOS",
    "Bolsas de basura para recoleccion de residuos hospital",
    "GUANTE NITRILO TALLA M",
    "JERINGA 10 CC",
    "GASA ESTERIL 10X10",
    "BOLSA DE BASURA 80X110",
    "PECHERA DESECHABLE",
    "COFIA DESECHABLE",
    "DESINFECTANTES DE SUPERFICIE",
    "INSUMOS ASEO ESCUELA",
    "PRODUCTOS ASEO",
    "UTILES ASEO",
    "ADQ. ART. DE ASEO",
])
def test_real_insumos_singular_y_abreviaturas(real, nombre):
    assert real.es_candidata(nombre)
    assert real.evaluar(nombre=nombre).rubro == "insumos_medicos_aseo"


@pytest.mark.parametrize("nombre", [
    "ADQUISICION ROPA DE TRABAJO Y EPP: ZAPATOS DE SEGURIDAD, GUANTES DE CUERO Y CASCOS",
    "Guantes de soldador y guantes anticorte para taller municipal",
    "Mascarilla laringea desechable",
    "Cloro gas para sistemas de agua potable rural APR",
    "SERV. ASEO E INSUMOS DE ASEO CESFAM",
    "Serv. de Aseo con provision de insumos de aseo",
    "SERVICIO DE RECOLECCION DE RESIDUOS SOLIDOS DOMICILIARIOS",
    "ADQUISICIÓN DE MEDICAMENTOS E INSUMOS MEDICOS",
])
def test_real_exclusiones(real, nombre):
    assert not real.es_candidata(nombre)
    assert not real.evaluar(nombre=nombre).coincide


def test_real_alertas_regulatorias(real):
    assert real.alertas("Guantes de látex talla M") and real.alertas("Respirador N95")
    assert real.alertas("Jeringa 10 cc") and real.alertas("Cloro 5 litros")
    assert real.alertas("Guantes de nitrilo", "Papel higiénico", "Mascarilla 3 pliegues") == []
    assert real.solo_regulados(["alcohol gel", "desinfectante"])
    assert not real.solo_regulados(["alcohol gel", "papel higienico"])
    assert not real.solo_regulados([])
