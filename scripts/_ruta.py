"""Permite ejecutar los scripts sin instalar el paquete."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
