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
_CONECTORES = {"de", "del", "en", "para", "el", "la", "los", "las", "al"}
_CONECTOR_OPCIONAL = r"\s+(?:(?:de|del|en|para|el|la|los|las|al)\s+){0,2}"
_UNIDADES = (r"(?:unidad|departamento|depto|direccion|division|subdireccion|seccion|oficina|area|"
             r"jefatura|gerencia|subgerencia|subdepartamento|coordinacion|encargad[oa]|jef[ea])")


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin puntuación y con espacios simples."""
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", str(texto))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", _PUNTUACION.sub(" ", sin_tildes.lower())).strip()


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
    ignorar: re.Pattern | None = None              # frases que se borran (unidades, etc.)
    unidades: re.Pattern | None = None             # "Depto. de <palabra clave>"
    detectar_en_descripcion: bool = True
    usar_clasificacion_onu: bool = True            # categoría / producto ONU de Mercado Público

    def base(self, texto_norm: str) -> str:
        """Borra nombres de unidades ("Depto. de Control de Gestión") y frases ignoradas."""
        return _quitar(self.unidades, _quitar(self.ignorar, texto_norm))

    def _tramos_excluidos(self, texto_norm: str) -> list[tuple[int, int]]:
        return [(m.start(), m.end()) for p in (self.excluir, self.excluir_salvo_clave)
                if p is not None for m in p.finditer(texto_norm)]

    def claves(self, texto_norm: str) -> set[str]:
        """Palabras clave del texto, sin contar las que quedan DENTRO de una frase
        excluida ("mascarilla" en "mascarilla laríngea"). Una clave que contiene a
        la exclusión sí cuenta ("arquitectura de información" ⊃ "arquitectura")."""
        if self.incluir is None or not texto_norm:
            return set()
        texto = self.base(texto_norm)
        excluidos = self._tramos_excluidos(texto)
        return {
            normalizar(m.group(0)) for m in self.incluir.finditer(texto)
            if not any(a <= m.start() and m.end() <= b for a, b in excluidos)
        }

    def excluido(self, nombre_norm: str) -> bool:
        nombre = self.base(nombre_norm)
        if self.excluir is not None and self.excluir.search(nombre):
            return True
        if self.excluir_salvo_clave is not None and self.excluir_salvo_clave.search(nombre):
            return not self.claves(nombre)
        return False

    def tiene_candidata(self, texto_norm: str) -> bool:
        return self.candidatas is not None and bool(self.candidatas.search(self.base(texto_norm)))


@dataclass
class Resultado:
    rubro: str | None = None            # clave del rubro con más coincidencias
    rubro_nombre: str | None = None
    rubros: list[str] = field(default_factory=list)
    palabras: list[str] = field(default_factory=list)
    solo_regulados: bool = False        # todo lo detectado es producto con alerta regulatoria
    excluido: bool = False              # (ítems) descartado por una exclusión explícita

    @property
    def coincide(self) -> bool:
        return self.rubro is not None


@dataclass
class Alerta:
    patron: re.Pattern
    nota: str
    excepto: re.Pattern | None = None

    def aplica(self, texto_norm: str) -> bool:
        return bool(self.patron.search(_quitar(self.excepto, texto_norm)))


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
            claves = datos.get("palabras_clave") or []
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
                ignorar=_patron(datos.get("ignorar") or []),
                unidades=re.compile(
                    rf"\b{_UNIDADES}\s+(?:de\s+|del\s+)?(?:la\s+|el\s+|los\s+|las\s+)?(?:{alts})"
                    rf"(?:\s+(?:y|e)\s+(?:{alts}))*\b") if alts else None,
                detectar_en_descripcion=bool(datos.get("detectar_en_descripcion", True)),
                usar_clasificacion_onu=bool(datos.get("usar_clasificacion_onu", True)),
            ))
        self._alertas = []
        for a in alertas_regulatorias or []:
            patron = _patron(a.get("palabras") or [])
            if patron is not None and a.get("nota"):
                self._alertas.append(Alerta(patron, a["nota"], _patron(a.get("excepto") or [])))

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
            if rubro.claves(nombre_norm) or rubro.tiene_candidata(nombre_norm):
                return True
        return False

    def evaluar(self, *descripcion: str | None, nombre: str | None = None, items=(), items_onu=()) -> Resultado:
        """`items`: texto libre de cada línea; `items_onu`: producto/categoría según el
        clasificador ONU (cuentan solo si el rubro tiene usar_clasificacion_onu)."""
        nombre_norm = normalizar(nombre)
        fuerte = _unir([nombre, *items])
        onu = _unir(items_onu)
        libre = _unir(descripcion)
        hallazgos: list[tuple[Rubro, set[str]]] = []
        for rubro in self.rubros:
            if rubro.incluir is None or rubro.excluido(nombre_norm):
                continue
            fuertes = rubro.claves(fuerte) | (rubro.claves(onu) if rubro.usar_clasificacion_onu else set())
            en_descripcion = rubro.claves(libre)
            if not fuertes and not (rubro.detectar_en_descripcion and en_descripcion):
                continue
            hallazgos.append((rubro, fuertes | en_descripcion))
        return self._resultado(hallazgos, f"{fuerte} {onu} {libre}")

    def _resultado(self, hallazgos, texto_norm: str) -> Resultado:
        if not hallazgos:
            return Resultado()
        hallazgos.sort(key=lambda h: len(h[1]), reverse=True)
        principal = hallazgos[0][0]
        return Resultado(
            rubro=principal.clave,
            rubro_nombre=principal.nombre,
            rubros=[r.clave for r, _ in hallazgos],
            palabras=sorted({p for _, ps in hallazgos for p in ps}),
            solo_regulados=self._solo_regulados(principal, texto_norm),
        )

    # -- Ítems de órdenes de compra ----------------------------------------
    def evaluar_item(self, producto: str | None, categoria: str | None = None,
                     especificacion: str | None = None) -> Resultado:
        """Un ítem se clasifica por su PRODUCTO; si el producto no trae palabra clave,
        por la categoría ONU (rubros con usar_clasificacion_onu) o por la
        especificación del comprador (rubros sin ella, p. ej. consultoría, donde la
        categoría ONU "consultoría de gestión" se usa para cualquier servicio).
        Las exclusiones se aplican al producto."""
        producto_norm = normalizar(producto or especificacion)
        categoria_norm = normalizar(categoria)
        especificacion_norm = normalizar(especificacion)
        hallazgos = []
        excluido = False
        for rubro in self.rubros:
            if rubro.incluir is None:
                continue
            if producto_norm and rubro.excluido(producto_norm):
                excluido = True
                continue
            claves = rubro.claves(producto_norm)
            if not claves:
                respaldo = categoria_norm if rubro.usar_clasificacion_onu else especificacion_norm
                claves = rubro.claves(respaldo)
            if claves:
                hallazgos.append((rubro, claves))
        resultado = self._resultado(hallazgos, f"{producto_norm} {categoria_norm}")
        resultado.excluido = excluido and not resultado.coincide
        return resultado

    # -- Alertas regulatorias ---------------------------------------------
    def alertas(self, *textos: str | None) -> list[str]:
        texto = _unir(textos)
        return [a.nota for a in self._alertas if a.aplica(texto)]

    def _solo_regulados(self, rubro: Rubro, texto_norm: str) -> bool:
        """True si hay alerta y, al borrar los productos con alerta, no queda
        ninguna palabra clave (todo lo que se compra es regulado)."""
        con_alerta = [a for a in self._alertas if a.aplica(texto_norm)]
        if not con_alerta:
            return False
        resto = texto_norm
        for a in con_alerta:
            resto = _quitar(a.patron, _quitar(a.excepto, resto))
        return not rubro.claves(resto)
