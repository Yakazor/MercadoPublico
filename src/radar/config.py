"""Carga de config.yaml y del ticket desde .env."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]


def cargar_config(ruta: str | Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def obtener_ticket() -> str:
    load_dotenv(RAIZ / ".env")
    ticket = os.getenv("MP_TICKET", "").strip()
    if not ticket:
        raise RuntimeError(
            "No se encontró MP_TICKET. Copia .env.example como .env y pega tu ticket."
        )
    return ticket


def ruta_proyecto(relativa: str) -> Path:
    return RAIZ / relativa
