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


@dataclass
class Rubro:
    clave: str
    nombre: str
    incluir: re.Pattern | None
    excluir: re.Pattern | None


@dataclass
class Resultado:
    rubro: str | None = None            # clave del rubro con más coincidencias
    rubro_nombre: str | None = None
    rubros: list[str] = field(default_factory=list)
    palabras: list[str] = field(default_factory=list)

    @property
    def coincide(self) -> bool:
        return self.rubro is not None


class FiltroRubros:
    def __init__(self, config_rubros: dict):
        self.rubros = [
            Rubro(
                clave=clave,
                nombre=datos.get("nombre", clave),
                incluir=_patron(datos.get("palabras_clave", [])),
                excluir=_patron(datos.get("excluir", [])),
            )
            for clave, datos in (config_rubros or {}).items()
        ]

    def evaluar(self, *textos: str | None) -> Resultado:
        texto = normalizar(" ".join(t for t in textos if t))
        hallazgos: list[tuple[Rubro, list[str]]] = []
        for rubro in self.rubros:
            if rubro.incluir is None:
                continue
            if rubro.excluir is not None and rubro.excluir.search(texto):
                continue
            palabras = sorted(set(rubro.incluir.findall(texto)))
            if palabras:
                hallazgos.append((rubro, palabras))

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
