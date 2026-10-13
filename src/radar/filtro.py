"""Detección de rubro por palabras clave configurables (config.yaml).

Cómo se comparan las frases (ver `_alternativa`):
- sin tildes, mayúsculas ni puntuación ("SERV.ASEO" = "serv aseo");
- cada palabra admite plural ("guante" = "guantes", "indicador" = "indicadores");
- entre palabras se admiten conectores ("productos de aseo" = "productos aseo" =
  "productos para el aseo");
- siempre por palabra completa ("aseo" no coincide con "paseo").

Una palabra clave que queda DENTRO de una frase excluida no cuenta: "Mascarilla
laríngea desechable" se descarta, pero "Mascarillas laríngeas, guantes y gasas" se
detecta por guantes/gasas. Los nombres de unidades ("Depto. de Control de Gestión")
y las frases de `ignorar` se borran antes de evaluar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_PUNTUACION = re.compile(r"[.\-_/,;:()\[\]\"'“”‘’·•]+")
_SIGLA = re.compile(r"\b(?:[a-z]\.){2,}")                 # "e.p.p." → "epp"
# Negaciones para alertas con `negada_si_contiene`: "libre de polvo, látex", "s/ látex".
_NEGACION = r"\b(?:sin|libres?|exentos?|no|ni|s)(?:\s+\S+){0,3}?\s+"
_CONECTORES = {"de", "del", "en", "para", "el", "la", "los", "las", "al"}
_CONECTOR_OPCIONAL = r"\s+(?:(?:de|del|en|para|el|la|los|las|al)\s+){0,2}"
# Solo se aplica fuera del nombre (descripción, ítems, especificaciones).
_UNIDADES = (r"(?:unidad|departamento|depto|dpto|direccion|division|subdireccion|secretaria|seccion|"
             r"oficina|area|jefatura|gerencia|subgerencia|subdepartamento|coordinacion|encargad[oa]|jef[ea])")
# "Área/oficina/sección de análisis de datos" suele ser el tema, no quien compra:
# solo se borran si siguen claves débiles ("Oficina de Control de Gestión").
_UNIDADES_INFORMALES = {"area", "oficina", "seccion"}
# "Fortalecer la unidad de gestión estratégica": la unidad es lo que se contrata.
_VERBOS_UNIDAD = {"fortalecer", "fortalecimiento", "implementar", "implementacion", "crear", "creacion",
                  "disenar", "diseno", "redisenar", "rediseno", "modernizar", "modernizacion",
                  "mejorar", "mejoramiento"}
_SEGMENTOS = re.compile(r"[,;\n]|\s+y\s+|\s+e\s+", re.IGNORECASE)


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin puntuación y con espacios simples."""
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", str(texto))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()
    sin_tildes = _SIGLA.sub(lambda m: m.group(0).replace(".", ""), sin_tildes)
    return re.sub(r"\s+", " ", _PUNTUACION.sub(" ", sin_tildes)).strip()


def _alternativa(frase: str) -> str | None:
    """Regex (sin bordes) para una frase, con plural y conectores opcionales."""
    tokens = normalizar(frase).split()
    if not tokens:
        return None
    # Conectores internos ("de", "para"…) se vuelven opcionales.
    palabras = [t for i, t in enumerate(tokens)
                if not (t in _CONECTORES and 0 < i < len(tokens) - 1)]
    return _CONECTOR_OPCIONAL.join(_singular_plural(t) for t in palabras)


def _singular_plural(t: str) -> str:
    """Regex que acepta singular y plural de una palabra escrita en cualquiera de
    las dos formas: guante/guantes, indicador/indicadores, detergente/detergentes."""
    if len(t) <= 2 or not t[-1].isalpha():
        return re.escape(t)
    if t.endswith("es") and len(t) > 4:
        return re.escape(t[:-2]) + "(?:es|e|s)?"
    if t.endswith("s") and len(t) > 3:
        return re.escape(t[:-1]) + "(?:es|s)?"
    return re.escape(t) + "(?:es|s)?"


def _alternativas(frases) -> str | None:
    alts = {a for f in (frases or []) if (a := _alternativa(f))}
    if not alts:
        return None
    return "|".join(sorted(alts, key=len, reverse=True))


def _patron(frases) -> re.Pattern | None:
    alts = _alternativas(frases)
    return re.compile(rf"\b(?:{alts})\b") if alts else None


def _quitar(patron: re.Pattern | None, texto: str) -> str:
    return patron.sub(" ", texto) if patron is not None and texto else texto


def _unir(textos) -> str:
    return normalizar(" ".join(t for t in textos if t))


@dataclass
class Rubro:
    clave: str
    nombre: str
    incluir: re.Pattern | None
    candidatas: re.Pattern | None = None
    excluir: re.Pattern | None = None              # en el nombre, siempre
    excluir_salvo_clave: re.Pattern | None = None  # en el nombre, salvo que quede palabra clave
    excluir_salvo_especifica: re.Pattern | None = None  # ídem, pero `no_rescatan` no basta
    ignorar: re.Pattern | None = None              # frases que se borran (unidades, etc.)
    unidades: re.Pattern | None = None             # "Depto. de <palabra clave>"
    debiles: re.Pattern | None = None              # claves que solas no bastan fuera del nombre
    no_rescatan: re.Pattern | None = None          # claves genéricas que no anulan una exclusión
    amplias: re.Pattern | None = None              # claves de categoría ("insumos médicos")
    especialidades: re.Pattern | None = None       # "angiografía": deciden los ítems
    genericas_especialidad: re.Pattern | None = None  # claves del nombre que ahí no bastan
    detectar_en_descripcion: bool = True
    usar_clasificacion_onu: bool = True            # categoría / producto ONU de Mercado Público
    # Ítems de OC: productos ONU genéricos que no cuentan como clave, y productos a
    # los que se les revisa la especificación del comprador (None = a todos).
    productos_genericos: re.Pattern | None = None
    especificacion_si_producto: re.Pattern | None = None

    def base(self, texto_norm: str, es_nombre: bool = False) -> str:
        """Borra frases ignoradas y, fuera del nombre, nombres de unidades
        ("Depto. de Control de Gestión"). En el nombre "Consultoría para la unidad
        de control de gestión" describe lo que se contrata: se conserva."""
        texto = _quitar(self.ignorar, texto_norm)
        return texto if es_nombre else self._sin_unidades(texto)

    def _sin_unidades(self, texto: str) -> str:
        if self.unidades is None or not texto:
            return texto

        def reemplazo(m: re.Match) -> str:
            previas = texto[:m.start()].split()[-3:]
            if _VERBOS_UNIDAD.intersection(previas):
                return m.group(0)
            if m.group("unidad") in _UNIDADES_INFORMALES and (
                    # "Asesoría en el área de control de gestión" = en el ámbito de.
                    previas[-2:] in (["en", "el"], ["en", "la"]) or not self._solo_debiles(m.group("claves"))):
                return m.group(0)
            return " "
        return self.unidades.sub(reemplazo, texto)

    def _solo_debiles(self, texto: str) -> bool:
        return self.debiles is not None and all(
            self.debiles.fullmatch(normalizar(m.group(0))) for m in self.incluir.finditer(texto))

    def _tramos_excluidos(self, texto_norm: str) -> list[tuple[int, int]]:
        return [(m.start(), m.end())
                for p in (self.excluir, self.excluir_salvo_clave, self.excluir_salvo_especifica,
                          self.especialidades)
                if p is not None for m in p.finditer(texto_norm)]

    def claves(self, texto_norm: str, es_nombre: bool = False) -> set[str]:
        """Palabras clave del texto, sin contar las que quedan DENTRO de una frase
        excluida ("mascarilla" en "mascarilla laríngea"). Una clave que contiene a
        la exclusión sí cuenta ("arquitectura de información" ⊃ "arquitectura")."""
        if self.incluir is None or not texto_norm:
            return set()
        texto = self.base(texto_norm, es_nombre)
        excluidos = self._tramos_excluidos(texto)
        return {
            normalizar(m.group(0)) for m in self.incluir.finditer(texto)
            if not any(a <= m.start() and m.end() <= b for a, b in excluidos)
        }

    def sin_debiles_solas(self, claves: set[str]) -> set[str]:
        """Fuera del nombre, una única palabra débil ("indicadores de gestión" en
        "reporte con indicadores de gestión") no basta para detectar."""
        if self.debiles is None or len(claves) != 1:
            return claves
        (clave,) = claves
        return set() if self.debiles.fullmatch(clave) else claves

    def excluido(self, nombre_norm: str) -> bool:
        nombre = self.base(nombre_norm, es_nombre=True)
        if self.excluir is not None and self.excluir.search(nombre):
            return True
        claves = None
        if self.excluir_salvo_especifica is not None and self.excluir_salvo_especifica.search(nombre):
            # Una clave genérica ("guantes", "cloro") no rescata: "EPP: guantes y lentes"
            # se descarta; "EPP: guantes, mascarillas y pecheras" no.
            claves = self.claves(nombre, es_nombre=True)
            if not self.rescatan(claves):
                return True
        if self.excluir_salvo_clave is not None and self.excluir_salvo_clave.search(nombre):
            # Aquí cualquier clave rescata: "Guantes de examen y sondas" se revisa.
            claves = self.claves(nombre, es_nombre=True) if claves is None else claves
            return not claves
        return False

    def tiene_candidata(self, nombre_norm: str) -> bool:
        return self.candidatas is not None and bool(
            self.candidatas.search(self.base(nombre_norm, es_nombre=True)))

    def es_especialidad(self, nombre_norm: str) -> bool:
        return self.especialidades is not None and bool(
            self.especialidades.search(self.base(nombre_norm, es_nombre=True)))

    def rescatan(self, claves: set[str]) -> set[str]:
        """Claves que no son genéricas (`no_rescatan`)."""
        return {c for c in claves if not (self.no_rescatan is not None and self.no_rescatan.fullmatch(c))}

    def claves_items(self, items_norm: list[str]) -> tuple[set[str], bool]:
        """(claves, todas_excluidas) de las líneas de una licitación. Las líneas
        excluidas ("Guante cabritilla soldador") no aportan claves; si TODAS lo están,
        lo que se compra no es del rubro aunque el nombre diga "Guantes"."""
        lineas = [t for t in items_norm if t]
        vigentes = [t for t in lineas if not self.excluido(t)]
        claves = self.sin_debiles_solas(self.claves(" ".join(vigentes)))
        return claves, bool(lineas) and not vigentes

    def revisa_especificacion(self, producto_norm: str) -> bool:
        return (not producto_norm or self.especificacion_si_producto is None
                or bool(self.especificacion_si_producto.search(producto_norm)))


@dataclass
class Resultado:
    rubro: str | None = None            # clave del rubro con más coincidencias
    rubro_nombre: str | None = None
    rubros: list[str] = field(default_factory=list)
    palabras: list[str] = field(default_factory=list)
    solo_regulados: bool = False        # todo lo detectado es producto con alerta regulatoria
    excluido: bool = False              # (ítems) descartado por una exclusión explícita
    excluidos: set[str] = field(default_factory=set)  # (ítems) rubros que lo excluyen

    @property
    def coincide(self) -> bool:
        return self.rubro is not None


@dataclass
class Alerta:
    patron: re.Pattern
    nota: str
    excepto: re.Pattern | None = None
    # Si el texto trae alguna de estas frases ("nitrilo"), una negación hasta 3
    # palabras antes anula la mención: "Guante nitrilo libre de polvo, látex".
    negada_si: re.Pattern | None = None
    negada: re.Pattern | None = None

    def aplica(self, texto_norm: str) -> bool:
        texto = _quitar(self.excepto, texto_norm)
        if self.negada_si is not None and self.negada_si.search(texto):
            texto = _quitar(self.negada, texto)
        return bool(self.patron.search(texto))

    def quitar(self, texto_norm: str) -> str:
        """El texto sin las menciones de la alerta (ni sus excepciones o negaciones)."""
        texto = _quitar(self.excepto, texto_norm)
        if self.negada_si is not None and self.negada_si.search(texto):
            texto = _quitar(self.negada, texto)
        return _quitar(self.patron, texto)


class FiltroRubros:
    """Aplica los rubros de config.yaml.

    - `es_candidata(nombre)`: filtro preliminar barato, solo con el nombre.
    - `evaluar(descripcion..., nombre=, items=)`: decisión final para una licitación.
      Cuenta si hay palabra clave en el NOMBRE o en los ÍTEMS; en la descripción
      general solo si el rubro tiene `detectar_en_descripcion: true`.
    - `evaluar_item(producto, categoria)`: un ítem de orden de compra.
    - `alertas(...)`: notas regulatorias (ISP) para los productos mencionados.
    """

    def __init__(self, config_rubros: dict, alertas_regulatorias: list[dict] | None = None):
        self.rubros = []
        for clave, datos in (config_rubros or {}).items():
            datos = datos or {}
            debiles = datos.get("palabras_debiles") or []
            claves = list(datos.get("palabras_clave") or []) + list(debiles)
            alts = _alternativas(claves)
            # "excluir" (formato antiguo) se trata como exclusión en el nombre.
            duras = list(datos.get("excluir_en_nombre") or []) + list(datos.get("excluir") or [])
            self.rubros.append(Rubro(
                clave=clave,
                nombre=datos.get("nombre", clave),
                incluir=_patron(claves),
                candidatas=_patron(datos.get("palabras_candidatas") or []),
                excluir=_patron(duras),
                excluir_salvo_clave=_patron(datos.get("excluir_en_nombre_salvo_clave") or []),
                excluir_salvo_especifica=_patron(datos.get("excluir_en_nombre_salvo_clave_especifica") or []),
                ignorar=_patron(datos.get("ignorar") or []),
                unidades=re.compile(
                    rf"\b(?P<unidad>{_UNIDADES})\s+(?:de\s+|del\s+)?(?:la\s+|el\s+|los\s+|las\s+)?"
                    rf"(?P<claves>(?:{alts})(?:\s+(?:y|e)\s+(?:{alts}))*)\b") if alts else None,
                debiles=_patron(debiles),
                no_rescatan=_patron(datos.get("no_rescatan") or []),
                amplias=_patron(datos.get("palabras_amplias") or []),
                especialidades=_patron(datos.get("especialidades") or []),
                genericas_especialidad=_patron(datos.get("claves_genericas_en_especialidad") or []),
                detectar_en_descripcion=bool(datos.get("detectar_en_descripcion", True)),
                usar_clasificacion_onu=bool(datos.get("usar_clasificacion_onu", True)),
                productos_genericos=_patron(datos.get("productos_genericos") or []),
                especificacion_si_producto=_patron(datos.get("especificacion_si_producto") or []),
            ))
        self._alertas = []
        for a in alertas_regulatorias or []:
            alts = _alternativas(a.get("palabras") or [])
            if alts and a.get("nota"):
                self._alertas.append(Alerta(
                    re.compile(rf"\b(?:{alts})\b"), a["nota"], _patron(a.get("excepto") or []),
                    negada_si=_patron(a.get("negada_si_contiene") or []),
                    negada=re.compile(rf"{_NEGACION}(?:{alts})\b"),
                ))

    @classmethod
    def desde_config(cls, config: dict) -> "FiltroRubros":
        return cls(config.get("rubros") or {}, config.get("alertas_regulatorias"))

    # -- Licitaciones y nombres -------------------------------------------
    def es_candidata(self, nombre: str | None) -> bool:
        """¿Vale la pena pedir el detalle? Palabra clave o candidata en el nombre,
        sin exclusiones. La decisión final la toma `evaluar`."""
        nombre_norm = normalizar(nombre)
        if not nombre_norm:
            return False
        for rubro in self.rubros:
            if rubro.incluir is None or rubro.excluido(nombre_norm):
                continue
            if rubro.claves(nombre_norm, es_nombre=True) or rubro.tiene_candidata(nombre_norm):
                return True
        return False

    def evaluar(self, *descripcion: str | None, nombre: str | None = None, items=(), items_onu=()) -> Resultado:
        """`items`: texto libre de cada línea; `items_onu`: producto/categoría según el
        clasificador ONU (cuentan solo si el rubro tiene usar_clasificacion_onu)."""
        nombre_norm = normalizar(nombre)
        lineas = [normalizar(t) for t in items if t]
        items_norm = " ".join(lineas)
        onu = _unir(items_onu)
        libre = _unir(descripcion)
        hallazgos: list[tuple[Rubro, set[str]]] = []
        for rubro in self.rubros:
            if rubro.incluir is None or rubro.excluido(nombre_norm):
                continue
            en_nombre = rubro.claves(nombre_norm, es_nombre=True)
            en_items, items_excluidos = rubro.claves_items(lineas)
            # "Guantes" cuyos ítems son todos "guante cabritilla soldador": se descarta,
            # salvo que el nombre traiga una clave específica ("Jeringas").
            if items_excluidos and not rubro.rescatan(en_nombre):
                continue
            # "Insumos médicos para angiografía": deciden los ítems escritos por el
            # comprador; no cuentan las claves genéricas del nombre, la descripción
            # ni la clasificación ONU.
            especialidad = rubro.es_especialidad(nombre_norm)
            if especialidad and rubro.genericas_especialidad is not None:
                en_nombre = {c for c in en_nombre if not rubro.genericas_especialidad.fullmatch(c)}
            usa_onu = rubro.usar_clasificacion_onu and not especialidad
            fuertes = (en_nombre | en_items
                       | (rubro.sin_debiles_solas(rubro.claves(onu)) if usa_onu else set()))
            en_descripcion = set() if especialidad else rubro.claves(libre)
            # Descripción: siempre si el rubro lo permite; si no, solo cuando el nombre
            # ya era candidato ("Consultoría…") y la descripción trae 2+ claves distintas.
            descripcion_cuenta = rubro.detectar_en_descripcion or (
                rubro.tiene_candidata(nombre_norm) and len(en_descripcion) >= 2)
            if not fuertes and not (descripcion_cuenta and en_descripcion):
                continue
            hallazgos.append((rubro, fuertes | en_descripcion))
        return self._resultado(hallazgos, f"{nombre_norm} {items_norm} {onu} {libre}",
                               _segmentos(nombre), lineas)

    def _resultado(self, hallazgos, texto_norm: str, segmentos: list[str] | None = None,
                   lineas: list[str] | None = None) -> Resultado:
        if not hallazgos:
            return Resultado()
        hallazgos.sort(key=lambda h: len(h[1]), reverse=True)
        principal = hallazgos[0][0]
        return Resultado(
            rubro=principal.clave,
            rubro_nombre=principal.nombre,
            rubros=[r.clave for r, _ in hallazgos],
            palabras=sorted({p for _, ps in hallazgos for p in ps}),
            solo_regulados=self._solo_regulados(principal, texto_norm, segmentos or [], lineas or []),
        )

    # -- Ítems de órdenes de compra ----------------------------------------
    def respaldo_por_nombre(self, nombre: str | None) -> Resultado:
        """Rubro del nombre de una OC para clasificar su único ítem genérico ("Compra
        de guantes de nitrilo" + "NITRIDERM M CAJA 100"). Solo en rubros de productos
        (usar_clasificacion_onu) y si el nombre dice QUÉ producto es: "Compra de
        insumos médicos" (clave amplia) puede traer un monitor o un despacho."""
        nombre_norm = normalizar(nombre)
        hallazgos = []
        for rubro in self.rubros:
            if rubro.incluir is None or not rubro.usar_clasificacion_onu or rubro.excluido(nombre_norm):
                continue
            claves = rubro.claves(nombre_norm, es_nombre=True)
            if any(not (rubro.amplias is not None and rubro.amplias.fullmatch(c)) for c in claves):
                hallazgos.append((rubro, claves))
        return self._resultado(hallazgos, nombre_norm, _segmentos(nombre))

    def evaluar_item(self, producto: str | None, categoria: str | None = None,
                     especificacion: str | None = None, especificacion_proveedor: str | None = None) -> Resultado:
        """Un ítem se clasifica por su PRODUCTO; si el producto no trae palabra clave,
        por la categoría ONU (rubros con usar_clasificacion_onu) o por la
        especificación del comprador (rubros sin ella, p. ej. consultoría, donde la
        categoría ONU "consultoría de gestión" se usa para cualquier servicio). En
        esos rubros la especificación solo se revisa si el producto es compatible
        (`especificacion_si_producto`): "Servicios de catering" para una "jornada de
        plan estratégico" no es consultoría.
        Las exclusiones se revisan en el producto y en ambas especificaciones
        ("Guantes de protección" + "guante de cuero para soldador")."""
        desde_especificacion = not producto
        producto_norm = normalizar(producto or especificacion)
        categoria_norm = normalizar(categoria)
        especificacion_norm = normalizar(especificacion)
        proveedor_norm = normalizar(especificacion_proveedor)
        hallazgos = []
        excluidos = set()
        for rubro in self.rubros:
            if rubro.incluir is None:
                continue
            if any(t and rubro.excluido(t) for t in (producto_norm, especificacion_norm, proveedor_norm)):
                excluidos.add(rubro.clave)
                continue
            # "Servicios de consultoría de gestión" (producto ONU de cualquier servicio
            # profesional) no cuenta por sí mismo: se mira la especificación.
            generico = rubro.productos_genericos is not None and bool(
                rubro.productos_genericos.fullmatch(producto_norm))
            claves = set() if generico else rubro.claves(producto_norm, es_nombre=not desde_especificacion)
            if desde_especificacion:
                claves = rubro.sin_debiles_solas(claves)
            if not claves:
                if rubro.usar_clasificacion_onu:
                    respaldo = categoria_norm
                else:
                    respaldo = especificacion_norm if rubro.revisa_especificacion(producto_norm) else ""
                claves = rubro.sin_debiles_solas(rubro.claves(respaldo))
            if claves:
                hallazgos.append((rubro, claves))
        resultado = self._resultado(hallazgos, f"{producto_norm} {categoria_norm}", [producto_norm])
        resultado.excluidos = excluidos
        resultado.excluido = bool(excluidos) and not resultado.coincide
        return resultado

    # -- Alertas regulatorias ---------------------------------------------
    def alertas(self, *textos: str | None) -> list[str]:
        texto = _unir(textos)
        return [a.nota for a in self._alertas if a.aplica(texto)]

    def _solo_regulados(self, rubro: Rubro, texto_norm: str, segmentos: list[str],
                        lineas: list[str] = ()) -> bool:
        """True si hay alerta y todo lo que se compra es regulado: cada línea con
        palabra clave tiene también una alerta ("Guantes de examen de látex" →
        regulado; "Alcohol gel y papel higiénico" → no). Si los ítems traen claves,
        mandan los ítems ("Adquisición de guantes" + ítem "Guantes de látex" →
        regulado); si no, los segmentos del nombre."""
        if not any(a.aplica(texto_norm) for a in self._alertas):
            return False
        for partes in (lineas, segmentos):
            con_claves = [seg for seg in partes if seg and rubro.claves(seg)]
            if con_claves:
                return all(any(a.aplica(seg) for a in self._alertas) for seg in con_claves)
        resto = texto_norm
        for a in self._alertas:
            resto = a.quitar(resto)
        return not rubro.claves(resto)


def _segmentos(texto: str | None) -> list[str]:
    """Partes de un nombre separadas por comas, ";" o "y": "Alcohol gel, papel y cloro"."""
    return [normalizar(p) for p in _SEGMENTOS.split(texto or "") if p and p.strip()]
