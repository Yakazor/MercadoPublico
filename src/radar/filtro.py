"""Detección de rubro por palabras clave configurables (config.yaml)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes y con espacios simples."""
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", str(texto))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip()


def _patron(palabras: list[str]) -> re.Pattern | None:
    palabras = [normalizar(p) for p in palabras or [] if normalizar(p)]
    if not palabras:
        return None
    # Bordes de palabra: "aseo" no coincide con "paseo".
    alternativas = "|".join(re.escape(p) for p in sorted(palabras, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternativas})\b")


def _unir(textos) -> str:
    return normalizar(" ".join(t for t in textos if t))


@dataclass
class Rubro:
    clave: str
    nombre: str
    incluir: re.Pattern | None
    candidatas: re.Pattern | None = None
    excluir: re.Pattern | None = None            # en el nombre, siempre
    excluir_salvo_clave: re.Pattern | None = None  # en el nombre, salvo que traiga palabra clave

    def excluido(self, nombre_norm: str) -> bool:
        if self.excluir is not None and self.excluir.search(nombre_norm):
            return True
        if self.excluir_salvo_clave is not None and self.excluir_salvo_clave.search(nombre_norm):
            return not (self.incluir is not None and self.incluir.search(nombre_norm))
        return False


@dataclass
class Resultado:
    rubro: str | None = None            # clave del rubro con más coincidencias
    rubro_nombre: str | None = None
    rubros: list[str] = field(default_factory=list)
    palabras: list[str] = field(default_factory=list)

    @property
    def coincide(self) -> bool:
        return self.rubro is not None


@dataclass
class Alerta:
    patron: re.Pattern
    nota: str


class FiltroRubros:
    """Aplica los rubros de config.yaml.

    - `es_candidata(nombre)`: filtro preliminar barato, solo con el nombre.
    - `evaluar(descripcion..., nombre=, items=)`: decisión final. Cuenta como
      detección si hay una palabra clave en el NOMBRE o en los ÍTEMS; la
      descripción libre solo suma palabras (suele mencionar unidades como
      "Departamento de Control de Gestión" que no describen lo que se compra).
    - `alertas(...)`: notas regulatorias (ISP) para los productos mencionados.
    """

    def __init__(self, config_rubros: dict, alertas_regulatorias: list[dict] | None = None):
        self.rubros = []
        for clave, datos in (config_rubros or {}).items():
            # "excluir" (formato antiguo) se trata como exclusión en el nombre.
            duras = list(datos.get("excluir_en_nombre", [])) + list(datos.get("excluir", []))
            self.rubros.append(Rubro(
                clave=clave,
                nombre=datos.get("nombre", clave),
                incluir=_patron(datos.get("palabras_clave", [])),
                candidatas=_patron(datos.get("palabras_candidatas", [])),
                excluir=_patron(duras),
                excluir_salvo_clave=_patron(datos.get("excluir_en_nombre_salvo_clave", [])),
            ))
        self._alertas = [
            Alerta(patron=p, nota=a["nota"])
            for a in (alertas_regulatorias or [])
            if (p := _patron(a.get("palabras", []))) is not None and a.get("nota")
        ]

    @classmethod
    def desde_config(cls, config: dict) -> "FiltroRubros":
        return cls(config.get("rubros", {}), config.get("alertas_regulatorias"))

    def es_candidata(self, nombre: str | None) -> bool:
        """¿Vale la pena pedir el detalle? Palabra clave o candidata en el nombre,
        sin exclusiones. La decisión final la toma `evaluar`."""
        nombre_norm = normalizar(nombre)
        if not nombre_norm:
            return False
        for rubro in self.rubros:
            if rubro.incluir is None or rubro.excluido(nombre_norm):
                continue
            if rubro.incluir.search(nombre_norm):
                return True
            if rubro.candidatas is not None and rubro.candidatas.search(nombre_norm):
                return True
        return False

    def evaluar(self, *descripcion: str | None, nombre: str | None = None, items=()) -> Resultado:
        nombre_norm = normalizar(nombre)
        fuerte = _unir([nombre, *items])
        libre = _unir(descripcion)
        hallazgos: list[tuple[Rubro, list[str]]] = []
        for rubro in self.rubros:
            if rubro.incluir is None or rubro.excluido(nombre_norm):
                continue
            fuertes = set(rubro.incluir.findall(fuerte))
            if not fuertes:
                continue
            hallazgos.append((rubro, sorted(fuertes | set(rubro.incluir.findall(libre)))))

        if not hallazgos:
            return Resultado()
        hallazgos.sort(key=lambda h: len(h[1]), reverse=True)
        principal = hallazgos[0][0]
        return Resultado(
            rubro=principal.clave,
            rubro_nombre=principal.nombre,
            rubros=[r.clave for r, _ in hallazgos],
            palabras=sorted({p for _, ps in hallazgos for p in ps}),
        )

    def evaluar_item(self, *textos_item: str | None) -> Resultado:
        """Un ítem (producto) se evalúa como si su texto fuera un nombre: aplica
        exclusiones (ej. "sonda") y exige una palabra clave en el propio ítem."""
        return self.evaluar(nombre=" ".join(t for t in textos_item if t))

    def alertas(self, *textos: str | None) -> list[str]:
        texto = _unir(textos)
        return [a.nota for a in self._alertas if a.patron.search(texto)]

    def solo_regulados(self, palabras: list[str]) -> bool:
        """True si TODAS las palabras detectadas corresponden a productos con alerta."""
        if not palabras or not self._alertas:
            return False
        return all(any(a.patron.search(normalizar(p)) for a in self._alertas) for p in palabras)
