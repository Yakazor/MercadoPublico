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
    assert real.evaluar(nombre="EPP Depto. Aseo y Ornato").rubro == "seguridad_epp"
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
    assert real.evaluar(nombre="Alcohol gel y desinfectante").solo_regulados
    assert not real.evaluar(nombre="Alcohol gel y papel higiénico").solo_regulados
    # Un genérico ("guantes") junto a su calificador regulado ("de látex") es solo regulado.
    assert real.evaluar(nombre="Guantes de látex talla M").solo_regulados


@pytest.mark.parametrize("texto", [
    "Guantes de nitrilo libres de látex", "Guantes de nitrilo sin látex", "Pintura látex blanca",
    "Circuito para respirador mecánico", "Monitor resistente a desinfectantes",
])
def test_real_alertas_sin_falsos_positivos(real, texto):
    assert real.alertas(texto) == []


@pytest.mark.parametrize("texto", ["Mascarilla N-95", "Respirador KN 95", "Alcohol en gel 1 litro",
                                   "Clorogel 5 L", "Guante estéril talla 7"])
def test_real_alertas_variantes(real, texto):
    assert real.alertas(texto)


# --- Segunda ronda de revisión: variantes cercanas --------------------------------

@pytest.mark.parametrize("nombre", [
    "Consultoría en arquitectura de información",
    "Consultoría en arquitectura empresarial y de procesos",
    "Asesoría para arquitectura de los datos institucionales",
    "Consultoría para mejorar la gestión de la Dirección de Obras Municipales",
    "Asesoría a la Dirección de Obras Hidráulicas",
])
def test_real_bi_candidatas_con_obras_o_arquitectura(real, nombre):
    assert real.es_candidata(nombre)
    items = ["Implementación de tableros Power BI e indicadores de gestión"]
    assert real.evaluar(nombre=nombre, items=items).rubro == "consultoria_gestion_bi"


def test_real_unidades_no_cuentan_como_bi(real):
    r = real.evaluar(nombre="Asesoría técnica para mantención de ascensores",
                     items=["Mantenimiento de ascensores",
                            "Mantención mensual edificio de la Unidad de Control de Gestión"])
    assert not r.coincide
    assert not real.evaluar(nombre="Construcción de tablero de control eléctrico sala de bombas").coincide


def test_real_descripcion_en_consultoria_exige_candidata_y_dos_claves(real):
    assert real.evaluar("Se requieren guantes de nitrilo talla M", nombre="Adquisición de insumos varios").coincide
    # Consultoría: con candidata en el nombre y 2+ claves distintas en la descripción, cuenta…
    assert real.evaluar("Implementar dashboards en Power BI", nombre="Servicio de consultoría").coincide
    # …con una sola clave, o sin candidata en el nombre, no.
    assert not real.evaluar("Implementar un tablero en Power BI", nombre="Servicio de consultoría").coincide
    assert not real.evaluar("Dashboards en Power BI", nombre="Adquisición de vehículos").coincide


@pytest.mark.parametrize("nombre", [
    "Insumos clinicos para Unidad de Hemodinamia",
    "Mascarillas laringeas, guantes y gasas para pabellon",
    "COMPRA DE MATERIAL DE LIMPIEZA", "PRODUCTO DE LIMPIEZA", "INSUMO DE ASEO",
    "ADQ. ART DE ASEO", "COMPRA ART DE ASEO", "ARTS. ASEO", "PRODUCTO ASEO", "INSUMO ASEO",
    "PRODUCTOS PARA ASEO", "INSUMOS PARA EL ASEO", "Bolsas de residuos 80x110",
])
def test_real_insumos_variantes(real, nombre):
    assert real.es_candidata(nombre)
    items = ["Guantes de procedimiento", "Gasas"] if "Hemodinamia" in nombre else []
    assert real.evaluar(nombre=nombre, items=items).rubro == "insumos_medicos_aseo", nombre


@pytest.mark.parametrize("nombre", [
    "Mascarilla laringea desechable",
    "Serv de Aseo con provision de insumos de aseo", "SERV.ASEO E INSUMOS DE ASEO CESFAM",
    "SERV.DE ASEO CON INSUMOS DE ASEO", "Serv de Limpieza y productos de limpieza",
    "SERV.LIMPIEZA Y PRODUCTOS DE LIMPIEZA", "Servs. de aseo e insumos de aseo",
    "Cloro para sistemas APR comuna",
    "Adquisición de cloro para sistemas de agua potable rural",
    # Decisión: "agua potable"/"APR" excluye siempre (también este caso mixto, poco frecuente).
    "Cloro y articulos de aseo para comite de agua potable rural",
    "Guante cabritilla soldador",
])
def test_real_exclusiones_variantes(real, nombre):
    assert not real.evaluar(nombre=nombre).coincide, nombre


@pytest.mark.parametrize("nombre", ["INDICADOR DE GESTION", "Planes estrategicos institucionales"])
def test_real_bi_singular_plural(real, nombre):
    assert real.evaluar(nombre=nombre).rubro == "consultoria_gestion_bi"


def test_clave_vacia_en_config_no_falla():
    f = FiltroRubros({"x": {"nombre": "X", "palabras_clave": ["guantes"], "excluir_en_nombre": None,
                            "excluir_en_nombre_salvo_clave": None, "palabras_candidatas": None}})
    assert f.evaluar(nombre="Guantes").coincide


# --- Tercera ronda ------------------------------------------------------------------

def test_real_palabras_debiles_solas_no_bastan_en_items(real):
    kine = real.evaluar(nombre="Servicios profesionales de kinesiología",
                        items=["10 sesiones; reporte con indicadores de gestión"])
    assert not kine.coincide
    assert real.evaluar(nombre="Servicio de consultoría",
                        items=["Tablero de control con indicadores de gestión"]).coincide
    # En el nombre, una débil sí basta.
    assert real.evaluar(nombre="Consultoría en control de gestión").rubro == "consultoria_gestion_bi"


@pytest.mark.parametrize("nombre", [
    "Consultoría en el área de control de gestión",
    "Asesoría para implementar unidad de control de gestión",
    "Consultoría para fortalecer la unidad de gestión estratégica",
])
def test_real_unidad_en_el_nombre_no_se_borra(real, nombre):
    assert real.evaluar(nombre=nombre).rubro == "consultoria_gestion_bi"


def test_real_descripcion_bi_con_candidata(real):
    r = real.evaluar("Se requiere apoyo en control de gestión e indicadores de gestión",
                     nombre="CONSULTORÍA PARA LA DIRECCIÓN DE SALUD MUNICIPAL")
    assert r.rubro == "consultoria_gestion_bi"


def test_real_item_excluido_por_especificacion(real):
    r = real.evaluar_item("Guantes de protección", None, "Guante de cuero para soldador, talla 10")
    assert not r.coincide and r.excluido
    assert real.evaluar_item("Guantes de procedimiento", None, "Nitrilo talla M").coincide
    assert not real.evaluar_item(None, None, "Sesiones de kinesiología; reporte con indicadores de gestión").coincide


@pytest.mark.parametrize("texto", [
    "Guante nitrilo libre de polvo y látex", "Guantes de nitrilo exentos de látex", "Guantes vinilo no látex",
])
def test_real_alertas_latex_negado(real, texto):
    assert real.alertas(texto) == []


def test_real_gel_y_ffp2(real):
    assert real.evaluar_item("Gel hidroalcohólico 500 ml").coincide and real.alertas("Gel hidroalcohólico 500 ml")
    assert real.evaluar_item("Clorogel 5 L").coincide
    assert real.alertas("Mascarilla FFP-2") and real.alertas("Mascarilla FFP 2")


@pytest.mark.parametrize("nombre,esperado", [
    ("Guantes de procedimiento de látex talla M", True),
    ("Guantes de examen de látex", True),
    ("Mascarillas N95", True),
    ("Alcohol gel y papel higiénico", False),
    ("Guantes de nitrilo, jeringas y gasas", False),
])
def test_real_solo_regulados_por_segmento(real, nombre, esperado):
    assert real.evaluar(nombre=nombre).solo_regulados is esperado



@pytest.mark.parametrize("nombre", [
    "Cloro granulado para tratamiento de agua",
    "Hipoclorito y cloro para planta de tratamiento de agua",
    "Cloro para sistema de agua rural",
])
def test_real_genericas_no_rescatan(real, nombre):
    assert not real.es_candidata(nombre) and not real.evaluar(nombre=nombre).coincide


def test_real_epp_con_insumos_medicos_se_conserva(real):
    assert real.evaluar(nombre="EPP: guantes, mascarillas y pecheras para CESFAM").coincide
    assert real.evaluar(nombre="EPP guantes de nitrilo talla M").coincide


def test_real_unidades_dpto_en_items(real):
    r = real.evaluar(nombre="Consultoria para estudio hidrogeologico sector norte",
                     items=["Dpto. de Planificación Estratégica y Control de Gestión"])
    assert not r.coincide


@pytest.mark.parametrize("nombre", [
    "Cloro para A.P.R. Los Maitenes",
    "Compra de guantes de proteccion personal para operarios",
    "Cloro liquido para potabilizacion de agua",
    "Compra de cloro para analizador de cloro residual",
    "Jeringas para inyector de medio de contraste",
])
def test_real_epp_agua_y_laboratorio_variantes(real, nombre):
    assert not real.es_candidata(nombre) and not real.evaluar(nombre=nombre).coincide


@pytest.mark.parametrize("nombre", [
    "Adquisicion de EPP: guantes y lentes",
    "Elementos de proteccion personal: guantes, lentes y zapatos",
    "Adquisicion de E.P.P. guantes y lentes",
    "Guantes y lentes de seguridad para funcionarios de obras",
    "Guantes de seguridad para personal de operaciones",
    "Adquisicion de EPP: guantes de seguridad y cascos para cuadrilla",
    "EPP Depto. Aseo y Ornato",
    "Adquisicion de EPP: guantes, lentes y cascos para cuadrilla",
])
def test_real_epp_es_seguridad_no_insumo_medico(real, nombre):
    """El EPP de trabajo (guantes de seguridad, lentes, cascos) es su propio rubro de
    reventa, no un insumo médico."""
    r = real.evaluar(nombre=nombre)
    assert r.rubro == "seguridad_epp", (nombre, r.rubro, r.palabras)


def test_normalizar_siglas_con_puntos():
    assert normalizar("E.P.P. y A.P.R.") == "epp y apr"
    assert normalizar("SERV.ASEO") == "serv aseo"


def test_real_items_todos_excluidos_descartan_nombre_generico(real):
    assert not real.evaluar(nombre="Guantes", items=["Guante cabritilla soldador"]).coincide
    assert not real.evaluar(nombre="Cloro", items=["Cloro granulado para sistema de agua potable rural"]).coincide
    assert real.evaluar(nombre="Guantes", items=["Guante nitrilo talla M"]).coincide
    # Un nombre con clave específica se conserva aunque el ítem traiga "medicamentos".
    assert real.evaluar(nombre="Jeringas", items=["Jeringa 3 ml para administración de medicamentos"]).coincide
    # Una línea excluida no aporta palabras.
    r = real.evaluar(nombre="Insumos médicos", items=["Guante cabritilla soldador", "Gasas 10x10"])
    assert "guante" not in r.palabras and "gasas" in r.palabras


@pytest.mark.parametrize("nombre,items,esperado", [
    ("Adquisición de guantes", ["Guantes de látex talla M", "Guantes quirúrgicos estériles N° 7"], True),
    ("Compra de guantes", ["Guante de procedimiento de látex talla S"], True),
    ("Adquisición de mascarillas", ["Mascarillas N95"], True),
    ("Adquisición de guantes", ["Guantes de látex talla M", "Guantes de nitrilo talla M"], False),
])
def test_real_solo_regulados_mandan_los_items(real, nombre, items, esperado):
    assert real.evaluar(nombre=nombre, items=items).solo_regulados is esperado


@pytest.mark.parametrize("texto", [
    "Guantes nitrilo libre de polvo, látex", "Guantes nitrilo (libre de polvo/látex)", "Guante nitrilo s/ látex",
    "Guante de nitrilo talla M, libre de polvo, látex",
])
def test_real_latex_negado_en_guantes_de_nitrilo(real, texto):
    assert real.alertas(texto) == []


def test_real_latex_sin_negacion_sigue_alertando(real):
    assert real.alertas("Guante de procedimiento látex sin polvo")
    assert real.alertas("Guantes de nitrilo y guantes de látex")
    assert real.alertas("Guante sin polvo, látex, talla M")


@pytest.mark.parametrize("nombre", [
    "Guantes anti-corte nivel 5", "Guantes anti corte para taller", "Guantes de soldadura para taller municipal",
    "Guantes negros tácticos para Carabineros", "Cloro para Servicio Sanitario Rural Los Robles",
    "Cloro para agua de bebida comité rural",
    "Suministro de cloro para comités de agua potable rural",
])
def test_real_epp_y_agua_rural_mas_variantes(real, nombre):
    assert not real.es_candidata(nombre) and not real.evaluar(nombre=nombre).coincide


@pytest.mark.parametrize("producto", [
    "GEL HIDRO-ALCOHOLICO 1L", "Gel hidro alcohólico 1 L", "Solución hidroalcohólica 500 ml", "Gel alcohólico 1 L",
    "Respirador N95", "Respirador KN95 caja 20", "Respirador FFP2 sin válvula",
])
def test_real_gel_y_respiradores_se_detectan_con_alerta(real, producto):
    assert real.evaluar_item(producto).coincide and real.alertas(producto)
    assert real.evaluar(nombre=f"Adquisición de {producto}").coincide


def test_real_respirador_mecanico_no_es_insumo(real):
    assert not real.evaluar(nombre="Circuito para respirador mecánico adulto").coincide


def test_real_item_excluido_por_especificacion_del_proveedor(real):
    r = real.evaluar_item("Guantes de protección", "Guantes", "Guante talla 10", "Guante de cuero para soldador marca X")
    assert not r.coincide and r.excluido
    assert not real.evaluar_item("Guantes", None, None, "Guante de seguridad multiflex").coincide


def test_real_respaldo_por_nombre_exige_producto_especifico(real):
    assert real.respaldo_por_nombre("Compra de guantes de nitrilo").coincide
    assert not real.respaldo_por_nombre("Compra de insumos médicos para pabellón").coincide
    assert not real.respaldo_por_nombre("Servicio de café para jornada de planificación estratégica").coincide


def test_real_ssr_servicio_de_salud_no_se_excluye(real):
    # "SSR" también es la sigla del Servicio de Salud del Reloncaví.
    assert real.evaluar(nombre="Guantes de nitrilo para SSR").coincide


@pytest.mark.parametrize("item", [
    "Servicio de apoyo al área de análisis de datos",
    "Profesional para la oficina de gestión de procesos",
    "Fortalecer la sección de análisis de datos",
    "Consultoría para fortalecer la unidad de gestión estratégica",
])
def test_real_unidad_como_tema_del_servicio_no_se_borra(real, item):
    assert real.evaluar(nombre="Servicio de consultoría", items=[item]).rubro == "consultoria_gestion_bi"


def test_real_unidad_compradora_sigue_sin_contar(real):
    for item in ["Solicitado por la Unidad de Control de Gestión", "Oficina de Control de Gestión",
                 "Depto. de Gestión Estratégica, edificio central"]:
        assert not real.evaluar(nombre="Servicio de consultoría", items=[item, "Sesiones de kinesiología"]).coincide
    assert real.evaluar("Apoyo al área de análisis de datos y visualización de datos",
                        nombre="Servicio de consultoría").coincide
    assert real.evaluar_item(None, "Servicios de consultoría de gestión", "Apoyo al área de análisis de datos").coincide


@pytest.mark.parametrize("nombre", [
    "Adquisición de guantes estériles y sondas de aspiración",
    "Insumos clinicos: sondas Foley y guantes de examen",
    "Guantes de examen y nebulizadores",
    "Bolsas de residuos y guantes para recolección",
])
def test_real_guantes_rescatan_exclusiones_clinicas(real, nombre):
    assert real.evaluar(nombre=nombre).rubro == "insumos_medicos_aseo"


def test_real_en_el_area_de_es_ambito_no_unidad(real):
    for item in ["Asesoría especializada en el área de inteligencia de negocios y análisis de datos",
                 "Asesoría en el área de control de gestión e indicadores de gestión"]:
        assert real.evaluar(nombre="Contratación de consultoría externa", items=[item]).coincide


def test_real_respaldo_por_nombre_ignora_unidades_de_bi(real):
    r = real.respaldo_por_nombre("Artículos de aseo para Depto. de Planificación Estratégica y Control de Gestión")
    assert not r.coincide  # "artículos de aseo" es amplia
    r = real.respaldo_por_nombre("Toallas de papel para Depto. de Planificación Estratégica y Control de Gestión")
    assert r.rubro == "insumos_medicos_aseo"


@pytest.mark.parametrize("nombre", [
    "ADQUISICIÓN DE INSUMOS MÉDICOS PARA ANGIOGRAFÍA Y HEMODINAMIA",
    "ADQUISICIÓN DE INSUMOS MÉDICOS PARA LOS SERVICIOS DE TRAUMATOLOGÍA Y CARDIOCIRUGÍA",
    "Adquisición de Insumos Médicos para Cirugía Robótica por Sistema de Suministro",
    "CONVENIO SUMINISTRO INSUMOS MEDICOS VARIOS PARA DIALISIS HOSPITAL VILLARRICA",
    "CONVENIO SUMINISTRO INSUMOS MEDICOS PARA OFTALMOLOGIA HOSPITAL VILLARRICA",
    "CONVENIO SUMINISTRO INSUMOS MEDICOS FORMALINA PARA EL HOSPITAL VILLARRICA",
    "BMC ADQ JERINGA INYECTORA PARA RESONADOR MAGNETICO",
    "221 - ADQUISICIÓN DE MASCARILLAS NEBULIZADOR APARATO DE FISIOTERAPIA Y AEROCÁMARA",
    "CAPS ADQ. DE MASCARILLA ANESTESIA Y OTROS INSUMOS",
])
def test_real_especialidades_clinicas_no_son_reventa(real, nombre):
    """Corrida real del 12-10-2026: dispositivos de especialidad, no productos de reventa."""
    assert not real.evaluar("Adquisición de insumos médicos según bases", nombre=nombre,
                            items=["Catéter angiográfico 5F", "Introductor valvulado"],
                            items_onu=["Jeringas", "Equipos médicos"]).coincide


def test_real_especialidad_con_lineas_de_reventa_se_detecta(real):
    r = real.evaluar(nombre="ADQUISICIÓN DE INSUMOS MÉDICOS PARA ANGIOGRAFÍA Y HEMODINAMIA",
                     items=["Catéter angiográfico 5F", "Guante de procedimiento nitrilo talla M", "Gasa 10x10"])
    assert r.rubro == "insumos_medicos_aseo" and "insumos medicos" not in r.palabras
    assert not real.evaluar(nombre="Jeringas para resonador", items=["Jeringa inyectora 200 ml"]).coincide


@pytest.mark.parametrize("nombre", [
    "Guantes y gasas para unidad de diálisis",
    "INSUMOS MEDICOS MES DE OCTUBRE PARA DEPTO DE SALUD",
    "Compra Insumos Clínicos – Clínicas Odontológicas: guantes nitrilo y jabón líquido",
    "CONVENIO DE SUMINISTRO DE GASAS GUANTES JERINGAS MASCARILLAS SUTURAS Y OTROS INSUMOS",
    "Mascarillas de 3 pliegues y mascarillas N95",
])
def test_real_insumos_de_reventa_se_conservan(real, nombre):
    assert real.evaluar(nombre=nombre).rubro == "insumos_medicos_aseo"


# --- Revisión del 13-10-2026 ---------------------------------------------------

def test_real_negacion_de_latex_no_cruza_lineas(real):
    nota = "Guantes de látex/quirúrgicos: registro ISP + conformidad por lote (DE 342/2004)"
    assert nota in real.alertas("GUANTE DE PROCEDIMIENTO NITRILO TALLA S", "GUANTE DE PROCEDIMIENTO LATEX TALLA S")
    assert nota in real.alertas("Guante nitrilo s/polvo talla M", "Guante látex talla M")
    assert nota in real.alertas("Guante vinilo talla S", "Guante quirúrgico estéril Nº 7")
    assert nota in real.alertas("CONVENIO SUMINISTRO Nº 45/2026 GUANTES DE LÁTEX Y NITRILO")
    assert nota in real.alertas("Guante nitrilo sin polvo, guante látex talla M")


@pytest.mark.parametrize("nombre,items", [
    ("Adquisición de alcohol gel y toallas de papel para CESFAM",
     ["Alcohol gel 70% bidón 5 litros", "Toalla interfoliada 250 hojas, caja 20 paquetes"]),
    ("Adquisición de artículos de aseo", ["Alcohol gel 1 litro", "Toalla interfoliada", "Lustramuebles"]),
    ("Adquisición de insumos de aseo", ["Jabón líquido y papel higiénico"]),
])
def test_real_solo_regulados_no_oculta_productos_no_regulados(real, nombre, items):
    r = real.evaluar(nombre=nombre, items=items)
    assert r.coincide and not r.solo_regulados


def test_real_exclusion_de_contexto_no_borra_linea_con_producto(real):
    r = real.evaluar(nombre="Adquisición de insumos clínicos para Posta Rural Quilaco",
                     items=["Jeringa desechable 3 ml para administración de medicamentos"])
    assert r.coincide
    r = real.evaluar_item("Jeringas", None, None, "Jeringa 3 ml c/aguja 21G, para administración de medicamentos")
    assert r.coincide


def test_real_soldadura_estrella_en_bolsas_no_excluye(real):
    assert real.evaluar(nombre="Adquisición de bolsas de basura 80x110 con soldadura estrella").coincide
    assert real.evaluar_item("Bolsas de basura", None, None, "BOLSA NEGRA 80X110 SOLDADURA ESTRELLA").coincide
    assert not real.evaluar(nombre="Guantes de soldadura para taller municipal").coincide


# --- Segunda revisión del 13-10-2026 -------------------------------------------

@pytest.mark.parametrize("producto,especificacion", [
    ("Desinfectantes", "Servicio de aseo integral recintos de salud"),
    ("Desinfectantes", "Servicio de limpieza y desinfección de ambulancias mensual"),
    ("Desinfectantes", "Cloro gas cilindro 68 kg planta APR"),
    ("Mascarillas", "Mascarilla laríngea desechable N°4"),
    ("Jeringas", "Jeringa para inyector de medio de contraste 200 ml"),
])
def test_real_producto_generico_no_anula_exclusion_de_la_especificacion(real, producto, especificacion):
    assert not real.evaluar_item(producto, None, especificacion).coincide


def test_real_linea_con_exclusion_dura_no_se_rescata(real):
    assert not real.evaluar(nombre="Adquisición de insumos clínicos para Imagenología",
                            items=["Jeringa para inyector de medio de contraste 200 ml"]).coincide


@pytest.mark.parametrize("especificacion,esperado", [
    (None, True),
    ("Según términos de referencia", True),
    ("Servicio de consultoría según propuesta técnica", True),
    ("Sesiones de kinesiología según propuesta", False),
    ("Microsoft 365 Business Standard según cotización", False),
    ("Curso manejo defensivo conductores, ver anexo", False),
    ("Contrato honorarios abogado", False),
])
def test_real_respaldo_servicio_solo_con_especificacion_de_tramite(real, especificacion, esperado):
    r = real.respaldo_servicio("Consultoría Power BI y gestión estratégica", "Servicios de consultoría de gestión",
                               especificacion)
    assert r.coincide is esperado


@pytest.mark.parametrize("nombre,lineas", [
    ("Adquisición de guantes de látex", ["GUANTE DE PROCEDIMIENTO, LATEX, TALLA M, CAJA 100"]),
    ("Adquisición de guantes de procedimiento", ["Guante procedimiento látex talla M"]),
    ("Adquisición de productos de limpieza", ["Cloro gel 1 L", "Desinfectante amonio cuaternario 5 L"]),
    ("Adquisición de guantes", ["Guantes de examen de látex | talla M"]),
])
def test_real_solo_regulados_por_linea_completa(real, nombre, lineas):
    assert real.evaluar(nombre=nombre, items=lineas).solo_regulados



def test_real_epp_industrial_es_vestuario_no_insumo_medico(real):
    """Desde 13-10-2026 hay rubros de reventa además de insumos: el EPP industrial con
    ropa o calzado es vestuario."""
    for nombre in ("ADQUISICION ROPA DE TRABAJO Y EPP: ZAPATOS DE SEGURIDAD, GUANTES DE CUERO Y CASCOS",
                   "Implementos de seguridad: guantes y botas para operarios"):
        r = real.evaluar(nombre=nombre)
        assert r.rubro == "vestuario_textiles" and "insumos_medicos_aseo" not in r.rubros, nombre


@pytest.mark.parametrize("nombre,rubro", [
    ("Adquisición de sillas y escritorios para oficinas municipales", "mobiliario"),
    ("Compra de mobiliario escolar: mesas y sillas", "mobiliario"),
    ("Suministro de lockers metálicos", "mobiliario"),
    ("Adquisición de artículos de oficina y resmas de papel", "oficina_libreria"),
    ("Compra de tóner para impresoras", "oficina_libreria"),
    ("Adquisición de notebooks y monitores", "computacion_electronica"),
    ("Compra de proyectores y data show para colegios", "computacion_electronica"),
    ("Adquisición de herramientas eléctricas: taladros y esmeriles", "ferreteria_herramientas"),
    ("Compra de pinturas y brochas para mantención de escuela", None),
    ("Materiales de ferretería para obras menores", "ferreteria_herramientas"),
    ("Adquisición de electrodomésticos: refrigerador y microondas", "hogar_menaje"),
    ("Compra de vajilla y menaje para casino", "hogar_menaje"),
    ("Adquisición de uniformes corporativos y calzado", "vestuario_textiles"),
    ("Ropa de trabajo para personal de la Dirección de Obras Municipales", "vestuario_textiles"),
    ("Compra de balones e implementos deportivos", "deporte_didactico"),
    ("Adquisición de material didáctico y juguetes para jardines infantiles", "deporte_didactico"),
])
def test_real_rubros_de_reventa(real, nombre, rubro):
    assert real.evaluar(nombre=nombre).rubro == rubro, nombre


@pytest.mark.parametrize("nombre", [
    "Servicio de mesa de ayuda informática",
    "Arriendo de mesas, sillas y toldos para evento",
    "Reparación de sillas de auditorio",
    "Mantención de impresoras y fotocopiadoras",
    "Arriendo de computadores",
    "Adquisición de monitor multiparámetro para UCI",
    "Herramientas de gestión para la planificación comunal",
    "Construcción de vestuarios y camarines estadio municipal",
    "Servicio de lavandería de ropa hospitalaria",
    "Instalación de juegos infantiles en plaza",
    "Adquisición de sillas de ruedas para pacientes",
    "Ventiladores mecánicos para UCI",
    "Pavimentación con carpeta asfáltica calle principal",
    "Remate de bienes muebles dados de baja",
])
def test_real_no_son_compras_de_reventa(real, nombre):
    r = real.evaluar(nombre=nombre)
    assert not r.coincide, (nombre, r.rubro, r.palabras)


# Falsos positivos del primer radar con los rubros de reventa (13-10-2026).
@pytest.mark.parametrize("nombre", [
    "Construcción Sobre Techo Dependencias INCA",
    "Curso de perfeccionamiento sobre estrategias e instrumentos de evaluación para docentes",
    "C.S. Insulina Glargina 300 Ui Ml Lápices Desechables",
    "INSUL GLULI 100UML SIN LAPIZ REUTIL+AG 10000023063",
    "CONVENIO CLAVO INTRAMEDULAR ARTRODESIS DE RODILLA",
    "PZM-SUM. TORNILLOS CANULADOS EQ COMODATO",
    "Convenio de insumos TMT Clavos para el Hospital Provincial de Ovalle",
    "BALONES DE ANGIOPLASTIA Y STENTS MEDICADOS",
    "SUMINISTRO DE ENDOP. BALÓN EXPANDIBLE CUBIERTA",
    "LAVADORAS ULTRASÓNICAS PARA CENTRAL DE ESTERILIZACIÓN APS CASTRO",
    "SERVICIO LAVADO CORTINAS 1 AÑO M.165 APOYO CLINICO",
    "Adquisición de 03 puertas de termo panel",
    "LIC. 91.26 ADQ. VENTILADORES M.T. Y MONITORES DES",
    "RPH - SENSOR NEONATAL Y ADULTO OXIMETRIA CON MONITORES ASOCIADOS",
    "Escáner de RX para el Complejo Fronterizo Vergara",
    "Ejecutivos de información monitores",
    "CONVENIO DE SUMINISTRO AMPLIFICACIÓN ILUMINACIÓN PANTALLA LED Y COMPLEMENTARIOS",
    "BOTA DE UNNA 10 A 105 CM X 9 A 10 M 1000022996",
    "CONVENIO SUMINISTRO PAQUETE DE ROPA PARA TRAUMATOLOGIA HOSPITAL VILLARRICA",
    "Tarjeta Tipo Gift Card para Vestuario ProRetención",
    "SERVICIOS DE EDICIONES LIBROS DE DERECHO, UNIVERSIDAD DE TALCA",
    "Concesión espacio públ. mobiliario publicitario",
    "RESTAURACION Y REACONDICIONAMIENTO DE MOBILIARIO",
    "SILLA RUED NEUR ADT RECL-BASC AS VARIOS CM 1000023259",
    "JGOD PPU 70-2026 AFL030 RADIER Y PINTURA E.A.",
    "DIPLOMADO EN GESTIÓN FINANCIERA PÚBLICA",
])
def test_real_falsos_positivos_de_reventa(real, nombre):
    r = real.evaluar(nombre=nombre)
    assert not r.coincide, (nombre, r.rubro, r.palabras)


@pytest.mark.parametrize("nombre,rubro", [
    # "Escritorio" de un computador o de útiles de oficina no es un mueble.
    ("ADQUISICION COMPUTADORES DE ESCRITORIO PARA DESAM", "computacion_electronica"),
    ("Adquisición de sobres americanos y carpetas", "oficina_libreria"),
    ("Adquisición de 10.000 Clavos Gemales", "ferreteria_herramientas"),
    ("Adquisición de mesa expandible para sala de reuniones", "mobiliario"),
])
def test_real_reventa_no_se_pierde(real, nombre, rubro):
    assert real.evaluar(nombre=nombre).rubro == rubro, nombre


def test_real_articulos_de_escritorio_no_son_mobiliario(real):
    r = real.evaluar(nombre="Adquisición de artículos de librería",
                     items=["Artículos de escritorio para alumnos"])
    assert r.rubro == "oficina_libreria"
    assert "mobiliario" not in r.rubros


def test_manda_el_rubro_del_nombre():
    rubros = {
        "vestuario": {"nombre": "Vestuario", "palabras_clave": ["uniformes"]},
        "computacion": {"nombre": "Computación", "palabras_clave": ["tablets", "notebooks", "computadores"]},
    }
    r = FiltroRubros(rubros).evaluar(nombre="Adquisición de uniformes y otros",
                                     items=["Tablets 10 pulgadas", "Notebook 14", "Computadores"])
    assert r.rubro == "vestuario"
    assert set(r.rubros) == {"vestuario", "computacion"}


def test_grupos_de_exclusion_compartidos():
    rubros = {"ferreteria": {"nombre": "Ferretería", "palabras_clave": ["clavos"],
                             "excluir_grupos": ["clinico"]}}
    f = FiltroRubros(rubros, grupos_exclusion={"clinico": ["intramedular"]})
    assert not f.evaluar(nombre="Clavo intramedular").coincide
    assert f.evaluar(nombre="Clavos de acero").coincide
    with pytest.raises(ValueError):
        FiltroRubros({"x": {"palabras_clave": ["a"], "excluir_grupos": ["no_existe"]}})


def test_item_oc_manda_el_rubro_del_producto():
    rubros = {
        "aseo": {"nombre": "Aseo", "palabras_clave": ["productos de aseo"]},
        "vestuario": {"nombre": "Vestuario", "palabras_clave": ["uniformes"]},
    }
    r = FiltroRubros(rubros).evaluar_item("Uniformes escolares", "Productos de aseo / Uniformes")
    assert r.rubro == "vestuario"


@pytest.mark.parametrize("producto,categoria,rubro", [
    # La categoría ONU de la ropa ("…productos de aseo personal") no es aseo.
    ("Uniformes escolares", "Ropa, maletas y productos de aseo personal / Ropa", "vestuario_textiles"),
    ("Trajes de hombre", "Ropa, maletas y productos de aseo personal / Ropa", "vestuario_textiles"),
    ("Papel para fotocopiadora o impresora", "", "oficina_libreria"),
    ("Planchas a vapor", "", "hogar_menaje"),
    # Productos clínicos o servicios con nombre de producto de reventa
    ("Aguja B Braun anestesia punta lapiz 27G", "", None),
    ("Cinta adhesiva medica 3M microporosa", "", None),
    ("Dispositivos de sujecion protesica o accesorios", "", None),
    ("Alargador venoso nemo neonatal 15 cm", "", None),
    ("Monitores o medidores de colesterol", "", None),
    ("Almohadillas cojines o almohadas para posicionar el enfermo", "", None),
    ("Plancha de cinc", "", None),
    ("Juntas obturadoras textiles", "", None),
    ("Escritores de libros", "", None),
    ("Software de desarrollo de plataforma web", "", None),
    ("Bodegaje de muebles o mobiliario", "", None),
])
def test_real_items_oc_de_reventa(real, producto, categoria, rubro):
    r = real.evaluar_item(producto, categoria)
    assert r.rubro == rubro, (producto, r.rubro, r.palabras)


# --- Rubros agregados tras el censo de grupos -------------------------------

@pytest.mark.parametrize("nombre,rubro", [
    ("Adquisición de materiales de construcción para viviendas de emergencia", "construccion_electricos"),
    ("Compra de cemento y planchas de yeso cartón", "construccion_electricos"),
    ("ADQUISICION DE BATERIAS RECARGABLES DE 12 VOLTS", "construccion_electricos"),
    ("Adquisición de luminarias y focos LED para gimnasio", "construccion_electricos"),
    ("Materiales eléctricos para departamento de operaciones", "construccion_electricos"),
    ("REPOSICION PHMETRO Y MANOMETRO HCM", "laboratorio"),
    ("Material de laboratorio para liceo técnico", "laboratorio"),
    ("Microscopios para laboratorio de ciencias", "laboratorio"),
    ("NEUMATICOS Y OTROS REPUESTOS", "repuestos_vehiculos"),
    ("Adquisición de aceites lubricantes de motor 15W-40 y aceites hidráulicos", "repuestos_vehiculos"),
    ("Repuestos para motoniveladora Caterpillar", "repuestos_vehiculos"),
    ("Extintores y señalética de evacuación", "seguridad_epp"),
    ("Conos viales y chalecos reflectantes", "seguridad_epp"),
    ("ADQUISICIÓN DE TROFEOS Y MEDALLAS PARA CAMPEONATO", "deporte_didactico"),
    ("Herramientas de jardín y cortacésped para áreas verdes", "ferreteria_herramientas"),
    ("Equipamiento de cocina para casino", "hogar_menaje"),
    ("Servidores NAS y UPS para la universidad", "computacion_electronica"),
    ("Curso de Excel avanzado y Power BI para funcionarios", "consultoria_gestion_bi"),
    # Siguen entrando (radar del 18-10)
    ("ADQUISICION 10 BATERIAS TB65 Y 01 ESTACION CARGA", "construccion_electricos"),
    ("ADQ. PUERTAS PARA DEPENDENCIAS DE LA DEAOPERPOL", "construccion_electricos"),
    ("Adquisición de Tubos Corrugados PAD HDPE", "construccion_electricos"),
    ("Suministro de Neumáticos para Vehículos Fiscales", "repuestos_vehiculos"),
    ("SP 780 ADQUISICION DE ELEMENTOS DE PROTECCION PERSONAL", "seguridad_epp"),
    ("INSUMOS LABORATORIO FISICA SEDE CHILOÉ", "laboratorio"),
])
def test_real_rubros_nuevos_detectan(real, nombre, rubro):
    r = real.evaluar(nombre=nombre)
    assert r.rubro == rubro, (nombre, r.rubro, r.palabras)


@pytest.mark.parametrize("nombre", [
    # Obras, servicios, instalación o material a granel: no es reventa
    "Suministro de Mezcla Asfáltica en Caliente para capa de protección",
    "SUM. 5.500M3 MATERIAL PETREO PINTO DRV ÑUBLE",
    "SERVICIO CONEXIONES ELECTRICAS DE VIVIENDAS",
    "Adquisición e instalación de sistemas fotovoltaicos",
    "Construcción de sede social con materiales de construcción",
    "Suministro Test reportado y Eq. comodato B. Sangre",
    "PP 38-2026 Reactivos Sección de Hematología",
    "ADQUISICION DE INSUMOS PARA TÉCNICA AUTOMATIZADA DE INMUNOHISTOQUÍMICA",
    "Mantención de equipos de laboratorio",
    "Adquisición de camioneta 4x4 para la municipalidad",
    "SUMINISTRO DE COMBUSTIBLE",
    "Servicio de mantención y repuestos de flota",
    "SERVICIO DE SEGURIDAD: VIGILANTES Y CCTV",
    "Recarga de extintores edificio consistorial",
    "PROVISIÓN E INSTALACIÓN DE SEÑALES VERTICALES",
    "Adquisición de chalecos antibalas",
    "Batería de test psicométricos",
    # Vistos en el radar del 18-10 con los 13 rubros
    "SUMINISTRO DE COMBUSTIBLE PARA MAQUINARIA Y GRUPOS ELECTRÓGENOS DE LA MUNICIPALIDAD",
    "PPTA 332-26 CONT SERV LIMPIEZA VIDRIOS EN ALTURA",
    "REP. Y REV. FIBRA VIDRIO PISCINA C.R. RALUNCO",
    "SERVICIO DE RECAMBIO DE 60 CÁMARAS DE SEGURIDAD",
    "DISEÑO CONSTRUCCIÓN PARQUE PUERTA NORTE DE CHILE",
    "CONSTRUCCION LUMINARIAS ORNAMENTALES EJE SERRANO -VALLENAR",
    "Construcción Estaciones de Carga de Bicicletas",
    "GBA INT (001-002-002) 92 GMC SERV. RESTAURACIÓN PUERTAS INMUEBLE FACH",
    "PP 88 INST. LUMINARIAS Y CAMARAS TIERRAS BLANCAS",
    "REPOSICIÓN E INTALACIÓN DE LUMINARIAS PÚBLICAS",
    "RAM REPUESTO CAMARA CEREC Nº 181420 COFACH",
])
def test_real_rubros_nuevos_descartan(real, nombre):
    r = real.evaluar(nombre=nombre)
    assert not r.coincide, (nombre, r.rubro, r.palabras)
