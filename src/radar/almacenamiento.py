"""Persistencia en SQLite y exportación diaria CSV/Excel para Power BI."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ESQUEMA = """
CREATE TABLE IF NOT EXISTS licitaciones (
    codigo              TEXT PRIMARY KEY,
    nombre              TEXT,
    organismo           TEXT,
    unidad_compra       TEXT,
    region              TEXT,
    comuna              TEXT,
    monto_estimado      REAL,
    moneda              TEXT,
    tipo                TEXT,
    fecha_publicacion   TEXT,
    fecha_cierre        TEXT,
    estado              TEXT,
    rubro               TEXT,
    rubro_nombre        TEXT,
    rubros_todos        TEXT,
    palabras_detectadas TEXT,
    dias_restantes      INTEGER,
    url                 TEXT,
    primera_deteccion   TEXT,
    ultima_actualizacion TEXT
);

CREATE TABLE IF NOT EXISTS ordenes_compra_items (
    codigo_oc               TEXT,
    correlativo             INTEGER,
    nombre_oc               TEXT,
    codigo_licitacion       TEXT,
    estado                  TEXT,
    fecha_creacion          TEXT,
    organismo               TEXT,
    region                  TEXT,
    proveedor               TEXT,
    rut_proveedor           TEXT,
    moneda                  TEXT,
    rubro                   TEXT,
    rubro_nombre            TEXT,
    palabras_detectadas     TEXT,
    producto                TEXT,
    categoria               TEXT,
    especificacion_comprador TEXT,
    especificacion_proveedor TEXT,
    unidad                  TEXT,
    cantidad                REAL,
    precio_unitario_neto    REAL,
    total_item              REAL,
    PRIMARY KEY (codigo_oc, correlativo)
);

CREATE TABLE IF NOT EXISTS ordenes_compra_dias (
    fecha        TEXT PRIMARY KEY,   -- días ya procesados (permite reanudar)
    procesado_en TEXT
);
"""


class BaseDatos:
    def __init__(self, ruta: str | Path):
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(ruta)
        self.con.executescript(ESQUEMA)

    def cerrar(self) -> None:
        self.con.close()

    # -- Licitaciones --------------------------------------------------
    def guardar_licitaciones(self, filas: list[dict]) -> int:
        """Inserta o actualiza; conserva la fecha de primera detección."""
        ahora = datetime.now().isoformat(sep=" ", timespec="seconds")
        for fila in filas:
            datos = fila | {"primera_deteccion": ahora, "ultima_actualizacion": ahora}
            columnas = list(datos)
            actualizar = ", ".join(
                f"{c}=excluded.{c}" for c in columnas if c not in ("codigo", "primera_deteccion")
            )
            self.con.execute(
                f"INSERT INTO licitaciones ({', '.join(columnas)}) "
                f"VALUES ({', '.join('?' * len(columnas))}) "
                f"ON CONFLICT(codigo) DO UPDATE SET {actualizar}",
                list(datos.values()),
            )
        self.con.commit()
        return len(filas)

    def depurar_vigentes(self, codigos_actuales: set[str], hoy: date | None = None) -> int:
        """Elimina vigentes que ya no pasan el filtro (p. ej. tras cambiar config.yaml)."""
        hoy = hoy or date.today()
        vigentes = [
            c for (c,) in self.con.execute(
                "SELECT codigo FROM licitaciones WHERE fecha_cierre IS NULL OR date(fecha_cierre) >= ?",
                [hoy.isoformat()],
            )
        ]
        sobran = [c for c in vigentes if c not in codigos_actuales]
        self.con.executemany("DELETE FROM licitaciones WHERE codigo = ?", [(c,) for c in sobran])
        self.con.commit()
        return len(sobran)

    def licitaciones_vigentes(self, hoy: date | None = None) -> pd.DataFrame:
        """Licitaciones con cierre hoy o después; días restantes recalculados."""
        hoy = hoy or date.today()
        df = pd.read_sql_query(
            "SELECT * FROM licitaciones WHERE fecha_cierre IS NULL OR date(fecha_cierre) >= ? "
            "ORDER BY fecha_cierre",
            self.con,
            params=[hoy.isoformat()],
        )
        cierre = pd.to_datetime(df["fecha_cierre"], errors="coerce")
        df["dias_restantes"] = (cierre.dt.normalize() - pd.Timestamp(hoy)).dt.days.astype("Int64")
        return df

    # -- Órdenes de compra --------------------------------------------
    def guardar_items_oc(self, filas: list[dict]) -> int:
        for fila in filas:
            columnas = list(fila)
            self.con.execute(
                f"INSERT OR REPLACE INTO ordenes_compra_items ({', '.join(columnas)}) "
                f"VALUES ({', '.join('?' * len(columnas))})",
                list(fila.values()),
            )
        self.con.commit()
        return len(filas)

    def dia_oc_procesado(self, fecha: date) -> bool:
        cur = self.con.execute("SELECT 1 FROM ordenes_compra_dias WHERE fecha = ?", [fecha.isoformat()])
        return cur.fetchone() is not None

    def marcar_dia_oc(self, fecha: date) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO ordenes_compra_dias VALUES (?, ?)",
            [fecha.isoformat(), datetime.now().isoformat(sep=" ", timespec="seconds")],
        )
        self.con.commit()

    def items_oc(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM ordenes_compra_items", self.con)


def exportar(df: pd.DataFrame, carpeta: str | Path, nombre: str, hoy: date | None = None) -> list[Path]:
    """Exporta CSV + Excel con fecha y una copia fija '<nombre>_actual' para Power BI."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    sello = (hoy or date.today()).isoformat()
    rutas = []
    for base in (f"{nombre}_{sello}", f"{nombre}_actual"):
        csv = carpeta / f"{base}.csv"
        xlsx = carpeta / f"{base}.xlsx"
        # utf-8-sig + ';' para que Excel en español abra bien las tildes y columnas.
        df.to_csv(csv, index=False, sep=";", encoding="utf-8-sig")
        df.to_excel(xlsx, index=False, sheet_name=nombre[:31])
        rutas += [csv, xlsx]
    return rutas
