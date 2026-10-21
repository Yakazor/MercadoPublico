"""Carga de config.yaml y del ticket desde .env."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]


def cargar_config(ruta: str | Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def obtener_ticket(variable: str | None = None) -> str:
    """Ticket de MP_TICKET; con `variable`, el de esa variable si está definida
    (p. ej. un ticket aparte para la API de Compra Ágil) y si no, MP_TICKET."""
    load_dotenv(RAIZ / ".env")
    ticket = (os.getenv(variable, "") if variable else "").strip() or os.getenv("MP_TICKET", "").strip()
    if not ticket:
        raise RuntimeError(
            "No se encontró MP_TICKET. Copia .env.example como .env y pega tu ticket."
        )
    return ticket


def ruta_proyecto(relativa: str) -> Path:
    return RAIZ / relativa


def hoy_chile() -> date:
    """Fecha actual en Chile (GitHub Actions corre en UTC: de noche ya es "mañana")."""
    return datetime.now(ZoneInfo("America/Santiago")).date()
