"""Persistencia en SQLite y exportación diaria CSV/Excel para Power BI."""
from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

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
    alertas_regulatorias TEXT,
    solo_regulados      INTEGER,
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
    alertas_regulatorias    TEXT,
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

-- Detalle compacto de cada licitación candidata: se reutiliza mientras no cambie
-- su fecha de cierre en el listado ni pasen `refrescar_detalle_licitacion_dias`.
CREATE TABLE IF NOT EXISTS licitaciones_detalle (
    codigo         TEXT PRIMARY KEY,
    cierre_listado TEXT,
    descargado     TEXT,
    detalle        BLOB              -- JSON comprimido (zlib)
);

-- Detalle compacto de cada OC candidata (también las que no tienen ítems del rubro):
-- permite reclasificar con otra config.yaml sin volver a descargar.
CREATE TABLE IF NOT EXISTS ordenes_compra_detalle (
    codigo_oc TEXT PRIMARY KEY,
    fecha     TEXT,
    detalle   BLOB                   -- JSON comprimido (zlib)
);

-- Listado liviano (código y nombre) de las OC de cada día: si config.yaml agrega
-- palabras clave, permite pedir solo las OC que ahora son candidatas.
CREATE TABLE IF NOT EXISTS ordenes_compra_listados (
    fecha   TEXT PRIMARY KEY,
    listado BLOB                     -- JSON comprimido (zlib) de [[codigo, nombre], ...]
);

-- OC recuperadas por config nueva cuyo detalle falló: se dejan tras 3 intentos.
CREATE TABLE IF NOT EXISTS ordenes_compra_fallos (
    codigo_oc TEXT PRIMARY KEY,
    intentos  INTEGER
);

CREATE TABLE IF NOT EXISTS ordenes_compra_intentos (
    fecha     TEXT PRIMARY KEY,      -- días con OC cuyo detalle falló
    intentos  INTEGER,
    pendientes TEXT                  -- códigos de OC que fallaron en el último intento
);
"""

# Columnas agregadas después de la primera versión: se añaden a bases antiguas
# (la base vive en la caché de GitHub Actions entre ejecuciones).
COLUMNAS_NUEVAS = {
    "licitaciones": {"alertas_regulatorias": "TEXT", "solo_regulados": "INTEGER"},
    "ordenes_compra_items": {"alertas_regulatorias": "TEXT"},
}


class BaseDatos:
    def __init__(self, ruta: str | Path):
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        # Espera hasta 60 s si otra ejecución local está escribiendo.
        self.con = sqlite3.connect(ruta, timeout=60)
        self.con.executescript(ESQUEMA)
        self._migrar()

    def _migrar(self) -> None:
        for tabla, columnas in COLUMNAS_NUEVAS.items():
            existentes = {fila[1] for fila in self.con.execute(f"PRAGMA table_info({tabla})")}
            for columna, tipo in columnas.items():
                if columna not in existentes:
                    self.con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
        self.con.commit()

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

    def guardar_detalle_licitacion(self, codigo: str, cierre_listado: str | None, detalle: dict,
                                   hoy: date) -> None:
        with self.con:
            self.con.execute(
                "INSERT OR REPLACE INTO licitaciones_detalle VALUES (?, ?, ?, ?)",
                [codigo, cierre_listado, hoy.isoformat(),
                 zlib.compress(json.dumps(detalle, ensure_ascii=False).encode())],
            )

    def detalle_licitacion(self, codigo: str) -> tuple[dict, str | None, date] | None:
        """(detalle, cierre del listado cuando se descargó, fecha de descarga)."""
        fila = self.con.execute("SELECT detalle, cierre_listado, descargado FROM licitaciones_detalle "
                                "WHERE codigo = ?", [codigo]).fetchone()
        if fila is None:
            return None
        return json.loads(zlib.decompress(fila[0])), fila[1], date.fromisoformat(fila[2])

    def podar_detalles_licitacion(self, activas: set[str]) -> int:
        """Borra los detalles de licitaciones que ya no están activas."""
        guardadas = [c for (c,) in self.con.execute("SELECT codigo FROM licitaciones_detalle")]
        sobran = [(c,) for c in guardadas if c not in activas]
        with self.con:
            self.con.executemany("DELETE FROM licitaciones_detalle WHERE codigo = ?", sobran)
        return len(sobran)

    def depurar_vigentes(self, conservar: set[str], hoy: date | None = None) -> int:
        """Elimina las vigentes que no están en `conservar` (ya no pasan el filtro,
        p. ej. tras cambiar config.yaml). `conservar` debe incluir las detectadas
        hoy Y las que no se pudieron revisar por un error de la API."""
        hoy = hoy or date.today()
        vigentes = [
            c for (c,) in self.con.execute(
                "SELECT codigo FROM licitaciones WHERE fecha_cierre IS NULL OR date(fecha_cierre) >= ?",
                [hoy.isoformat()],
            )
        ]
        sobran = [c for c in vigentes if c not in conservar]
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
            self._insertar_item_oc(fila)
        self.con.commit()
        return len(filas)

    def reemplazar_items_oc(self, codigo_oc: str, filas: list[dict]) -> int:
        """Deja en la base exactamente `filas` para esa OC (borra ítems que ya no
        pertenecen a un rubro o que la OC ya no trae). En una sola transacción."""
        with self.con:
            self._reemplazar_items(codigo_oc, filas)
        return len(filas)

    def guardar_oc(self, codigo_oc: str, fecha: date, detalle: dict, filas: list[dict]) -> int:
        """Detalle compacto de la OC + sus ítems del rubro, en una sola transacción."""
        with self.con:
            self.con.execute(
                "INSERT OR REPLACE INTO ordenes_compra_detalle VALUES (?, ?, ?)",
                [codigo_oc, fecha.isoformat(), zlib.compress(json.dumps(detalle, ensure_ascii=False).encode())],
            )
            self._reemplazar_items(codigo_oc, filas)
        return len(filas)

    def guardar_listado_oc(self, fecha: date, listado: list[dict], conservar_dias: int = 90) -> None:
        """Guarda código y nombre de las OC del día y borra listados de más de
        `conservar_dias` (para días más antiguos queda --reprocesar)."""
        pares = [[oc.get("Codigo"), oc.get("Nombre")] for oc in listado if oc.get("Codigo")]
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO ordenes_compra_listados VALUES (?, ?)",
                             [fecha.isoformat(), zlib.compress(json.dumps(pares, ensure_ascii=False).encode())])
            self.con.execute("DELETE FROM ordenes_compra_listados WHERE date(fecha) < date(?, ?)",
                             [fecha.isoformat(), f"-{conservar_dias} days"])

    def listados_oc(self) -> list[tuple[date, list[list[str]]]]:
        filas = self.con.execute("SELECT fecha, listado FROM ordenes_compra_listados ORDER BY fecha").fetchall()
        return [(date.fromisoformat(f), json.loads(zlib.decompress(b))) for f, b in filas]

    def sumar_fallo_oc(self, codigo_oc: str) -> int:
        with self.con:
            self.con.execute("INSERT INTO ordenes_compra_fallos VALUES (?, 1) "
                             "ON CONFLICT(codigo_oc) DO UPDATE SET intentos = intentos + 1", [codigo_oc])
        (n,) = self.con.execute("SELECT intentos FROM ordenes_compra_fallos WHERE codigo_oc = ?",
                                [codigo_oc]).fetchone()
        return n

    def fallos_oc(self) -> dict[str, int]:
        return dict(self.con.execute("SELECT codigo_oc, intentos FROM ordenes_compra_fallos"))

    def codigos_con_detalle(self) -> set[str]:
        return {c for (c,) in self.con.execute("SELECT codigo_oc FROM ordenes_compra_detalle")}

    def detalles_oc(self) -> list[tuple[str, dict]]:
        filas = self.con.execute("SELECT codigo_oc, detalle FROM ordenes_compra_detalle").fetchall()
        return [(codigo, json.loads(zlib.decompress(blob))) for codigo, blob in filas]

    def _reemplazar_items(self, codigo_oc: str, filas: list[dict]) -> None:
        self.con.execute("DELETE FROM ordenes_compra_items WHERE codigo_oc = ?", [codigo_oc])
        for fila in filas:
            self._insertar_item_oc(fila)

    def _insertar_item_oc(self, fila: dict) -> None:
        columnas = list(fila)
        self.con.execute(
            f"INSERT OR REPLACE INTO ordenes_compra_items ({', '.join(columnas)}) "
            f"VALUES ({', '.join('?' * len(columnas))})",
            list(fila.values()),
        )

    def dia_oc_procesado(self, fecha: date) -> bool:
        cur = self.con.execute("SELECT 1 FROM ordenes_compra_dias WHERE fecha = ?", [fecha.isoformat()])
        return cur.fetchone() is not None

    def marcar_dia_oc(self, fecha: date) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO ordenes_compra_dias VALUES (?, ?)",
            [fecha.isoformat(), datetime.now().isoformat(sep=" ", timespec="seconds")],
        )
        self.con.commit()

    def codigos_oc(self) -> set[str]:
        return {c for (c,) in self.con.execute("SELECT DISTINCT codigo_oc FROM ordenes_compra_items")}

    def registrar_intento_fallido(self, fecha: date, pendientes: list[str]) -> int:
        """Suma un intento fallido para el día y devuelve cuántos lleva."""
        with self.con:
            self.con.execute(
                "INSERT INTO ordenes_compra_intentos (fecha, intentos, pendientes) VALUES (?, 1, ?) "
                "ON CONFLICT(fecha) DO UPDATE SET intentos = intentos + 1, pendientes = excluded.pendientes",
                [fecha.isoformat(), ", ".join(pendientes)],
            )
        (n,) = self.con.execute("SELECT intentos FROM ordenes_compra_intentos WHERE fecha = ?",
                                [fecha.isoformat()]).fetchone()
        return n

    def registrar_pendiente(self, fecha: date) -> None:
        """Día que quedó a medias por tiempo: se reintenta aunque salga de la ventana
        (no cuenta como intento fallido)."""
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO ordenes_compra_intentos (fecha, intentos, pendientes) "
                             "VALUES (?, 0, '(sin tiempo)')", [fecha.isoformat()])

    def dias_pendientes(self) -> list[date]:
        """Días con intentos fallidos que aún no se marcan como procesados."""
        filas = self.con.execute(
            "SELECT fecha FROM ordenes_compra_intentos "
            "WHERE fecha NOT IN (SELECT fecha FROM ordenes_compra_dias) ORDER BY fecha"
        ).fetchall()
        return [date.fromisoformat(f) for (f,) in filas]

    def items_oc(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM ordenes_compra_items", self.con)


def texto_excel(valor):
    """Texto que Excel acepta: sin caracteres de control (algunas descripciones de la API
    los traen, p. ej. «10U\x02POCA», y openpyxl rechaza la planilla entera)."""
    return ILLEGAL_CHARACTERS_RE.sub("", valor) if isinstance(valor, str) else valor


def texto_en_celda(celda) -> None:
    """openpyxl guarda como fórmula todo texto que empieza con «=» («= a lo solicitado»): la
    planilla abre con #¿NOMBRE? o pide reparación. Para celdas con texto de compradores o
    proveedores, lo deja como texto (sin alterar lo que se ve)."""
    if celda.data_type == "f":
        celda.data_type = "s"


def sin_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Textos libres de compradores y proveedores que empiezan con = + - @ ("= a lo
    solicitado") se exportan con un apóstrofo delante: Excel no los evalúa como fórmula.
    También se les quitan los caracteres de control (`texto_excel`)."""
    def limpiar(v):
        v = texto_excel(v)
        return "'" + v if isinstance(v, str) and v[:1] and v[0] in "=+-@" else v

    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].map(limpiar)
    return df


def exportar(df: pd.DataFrame, carpeta: str | Path, nombre: str, hoy: date | None = None) -> list[Path]:
    """Exporta CSV + Excel con fecha y una copia fija '<nombre>_actual' para Power BI."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    sello = (hoy or date.today()).isoformat()
    rutas = []
    for base in (f"{nombre}_{sello}", f"{nombre}_actual"):
        csv = carpeta / f"{base}.csv"
        xlsx = carpeta / f"{base}.xlsx"
        # utf-8-sig + ';' + coma decimal para que Excel y Power BI en español (es-CL)
        # abran bien tildes, columnas y montos.
        seguro = sin_formulas(df)
        seguro.to_csv(csv, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        seguro.to_excel(xlsx, index=False, sheet_name=nombre[:31])
        rutas += [csv, xlsx]
    return rutas
