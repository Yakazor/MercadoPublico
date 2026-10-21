"""Compras Ágiles abiertas (API Compra Ágil v2) clasificadas por rubro.

La API v2 es distinta de la de licitaciones (v1):
- URL base `https://api2.mercadopublico.cl`, recursos `/v2/compra-agil` (listado)
  y `/v2/compra-agil/{codigo}` (detalle con productos solicitados);
- el ticket va en el encabezado HTTP `ticket`, no en la URL;
- HTTP 429 es un límite de ritmo (token bucket) que se recupera en minutos: se
  espera lo que diga Retry-After (una vez por corrida) y, si vuelve, se corta;
- las fechas vienen en hora de Chile aunque traigan "Z" al final; `fecha_cierre`
  llega como "2026-10-23 15:00" (sin "T" ni segundos);
- páginas de 50 pueden cortarse con HTTP 504: se usa un tamaño menor y, ante un
  504, se reintenta la página con 10.

Cada Compra Ágil se convierte a la forma de una licitación (`como_licitacion`)
para reutilizar el filtro de rubros, las alertas ISP, el presupuesto y el
dashboard sin cambios: el tipo queda "Compra Ágil".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .cliente_api import ErrorApi
from .filtro import FiltroRubros
from .licitaciones import clasificar

log = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.ERROR)

URL_BASE = "https://api2.mercadopublico.cl"
TIPO = "Compra Ágil"
URL_FICHA = "https://buscador.mercadopublico.cl/ficha?code={}"
TAMANO_MINIMO = 10   # mínimo de la API y tamaño que no se corta con 504


class ClienteCompraAgil:
    def __init__(
        self,
        ticket: str,
        base_url: str = URL_BASE,
        timeout: float = 60,
        pausa: float = 4.0,
        reintentos: int = 3,
        espera_inicial: float = 5.0,
        max_espera_429: float = 900,
    ):
        self.ticket = ticket
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pausa = pausa
        self.reintentos = reintentos
        self.espera_inicial = espera_inicial
        self._sesion = requests.Session()
        self._ultima_llamada = 0.0
        self.llamadas = 0
        self.max_espera_429 = max_espera_429
        self._esperado_429 = False

    @classmethod
    def desde_config(cls, config: dict, ticket: str) -> "ClienteCompraAgil":
        ca = config.get("compra_agil", {})
        return cls(
            ticket=ticket,
            base_url=ca.get("base_url", URL_BASE),
            timeout=ca.get("timeout_segundos", 60),
            pausa=ca.get("pausa_entre_llamadas_segundos", 4.0),
            reintentos=ca.get("reintentos", 3),
            espera_inicial=ca.get("espera_inicial_reintento_segundos", 5.0),
            max_espera_429=ca.get("max_espera_429_segundos", 900),
        )

    def listado(self, **params) -> dict:
        """payload del listado: {"items": [...], "paginacion": {...}}."""
        return self._get("/v2/compra-agil", params)

    def detalle(self, codigo: str) -> dict:
        return self._get(f"/v2/compra-agil/{requests.utils.quote(codigo, safe='')}", {})

    def _get(self, recurso: str, params: dict) -> dict:
        url = f"{self.base_url}{recurso}"
        consulta = {k: v for k, v in params.items() if v is not None}
        espera = self.espera_inicial
        intento = 0
        while True:
            transcurrido = time.monotonic() - self._ultima_llamada
            if transcurrido < self.pausa:
                time.sleep(self.pausa - transcurrido)
            try:
                resp = self._sesion.get(url, params=consulta, headers={"ticket": self.ticket}, timeout=self.timeout)
                self._ultima_llamada = time.monotonic()
                self.llamadas += 1
                datos = _leer_json(resp)
                if resp.ok and isinstance(datos, dict) and datos.get("success") == "OK":
                    return datos.get("payload") or {}
                mensaje = _mensaje(datos, resp)
                if resp.status_code in (401, 403):
                    raise ErrorApi(f"{recurso}: HTTP {resp.status_code} - {mensaje}", fatal=True)
                if resp.status_code == 429:
                    # Límite de ritmo: se recupera en minutos. Una sola espera por corrida
                    # (acotada) para no comerse el tiempo del workflow; si vuelve, se corta.
                    retry = str((getattr(resp, "headers", None) or {}).get("Retry-After") or "")
                    pausa_429 = float(retry) if retry.isdigit() else self.max_espera_429
                    if not self._esperado_429 and pausa_429 <= self.max_espera_429:
                        self._esperado_429 = True
                        log.warning("%s: HTTP 429 (límite de ritmo). Se espera %.0f s y se reintenta.", recurso, pausa_429)
                        time.sleep(pausa_429)
                        continue
                    raise ErrorApi(f"{recurso}: HTTP 429 - {mensaje}", temporal=True, fatal=True)
                if resp.status_code in (400, 404):
                    raise ErrorApi(f"{recurso} {consulta}: HTTP {resp.status_code} - {mensaje}")
                motivo = f"HTTP {resp.status_code} - {mensaje}"
                if resp.status_code == 504 and consulta.get("tamano_pagina", 0) > TAMANO_MINIMO:
                    raise ErrorPaginaGrande(motivo)
            except requests.RequestException as e:
                self._ultima_llamada = time.monotonic()
                motivo = f"error de red: {e.__class__.__name__}"
            if intento == self.reintentos:
                raise ErrorApi(f"{recurso}: falló tras {self.reintentos} reintentos ({motivo})", temporal=True)
            log.warning("%s: %s. Reintento en %.0f s", recurso, motivo, espera)
            time.sleep(espera)
            espera *= 2
            intento += 1


class ErrorPaginaGrande(Exception):
    """HTTP 504 con una página grande: se repite con páginas de 10."""


def _leer_json(resp):
    try:
        return resp.json()
    except ValueError:
        return None


def _mensaje(datos, resp) -> str:
    if isinstance(datos, dict):
        errores = datos.get("errors") or []
        if errores and isinstance(errores[0], dict):
            return str(errores[0].get("mensaje") or errores[0].get("codigo"))
    return (getattr(resp, "text", "") or "")[:200]


def fecha_chile(valor) -> str | None:
    """"2026-10-23 15:00" o "2026-10-23T15:00:00Z" → "2026-10-23T15:00:00" (hora de
    Chile: la "Z" es engañosa)."""
    if not valor:
        return None
    texto = str(valor).strip().removesuffix("Z").replace(" ", "T", 1)
    if len(texto) == 16:          # "2026-10-23T15:00": sin segundos
        texto += ":00"
    return texto[:19]


def ahora_chile() -> datetime:
    return datetime.now(ZoneInfo("America/Santiago")).replace(tzinfo=None)


def listar_publicadas(cliente: ClienteCompraAgil, regiones: list[int] | None = None, dias_publicacion: int = 15,
                      tamano_pagina: int = 25, max_paginas: int = 200, ahora: datetime | None = None,
                      hasta_monotonic: float | None = None) -> list[dict]:
    """Compras Ágiles abiertas a cotización publicadas en los últimos `dias_publicacion` días.

    `ahora` en hora de Chile: la API compara su hora de Chile marcada con "Z"."""
    ahora = ahora or ahora_chile()
    params = {
        "estado": "publicada",
        "publicado_desde": (ahora - timedelta(days=dias_publicacion)).strftime("%Y-%m-%dT00:00:00Z"),
        "ordenar_por": "FechaPublicacion",
        "region": ",".join(str(r) for r in regiones) if regiones else None,
    }
    items, pagina, tamano = [], 1, tamano_pagina
    while pagina <= max_paginas:
        if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
            log.warning("Sin tiempo: el listado quedó en la página %d (incompleto).", pagina - 1)
            break
        try:
            payload = cliente.listado(**params, tamano_pagina=tamano, numero_pagina=pagina)
        except ErrorPaginaGrande:
            # Mismas filas desde el principio con páginas de 10 (cambia la numeración).
            log.warning("HTTP 504 con páginas de %d: se sigue con páginas de %d.", tamano, TAMANO_MINIMO)
            pagina = (pagina - 1) * tamano // TAMANO_MINIMO + 1
            max_paginas = max_paginas * tamano // TAMANO_MINIMO   # mismo tope de compras
            tamano = TAMANO_MINIMO
            continue
        items += payload.get("items") or []
        total = (payload.get("paginacion") or {}).get("total_paginas") or 0
        if pagina == 1:
            log.info("Compras Ágiles publicadas: %s", (payload.get("paginacion") or {}).get("total_resultados"))
        if pagina >= total:
            break
        pagina += 1
    else:
        log.warning("Se alcanzó el máximo de %d páginas: el listado quedó incompleto.", max_paginas)
    # Sin repetidos (una compra puede moverse de página mientras se recorre el listado).
    vistos, unicos = set(), []
    for item in items:
        if item.get("codigo") and item["codigo"] not in vistos:
            vistos.add(item["codigo"])
            unicos.append(item)
    return unicos


def como_licitacion(ca: dict) -> dict:
    """Detalle de Compra Ágil con los campos de una licitación (ver `modelos.compactar_licitacion`).

    El producto ONU va en NombreProducto y lo que escribió el comprador en Descripcion,
    igual que en las licitaciones. Campos propios: Llamado (1 = primer llamado, solo
    empresas de menor tamaño; 2 = segundo llamado) y entrega."""
    institucion = ca.get("institucion") or {}
    fechas = ca.get("fechas") or {}
    presupuesto = ca.get("presupuesto") or ca.get("montos") or {}
    entrega = ca.get("entrega") or {}
    convocatoria = ca.get("convocatoria") or {}
    # Sin monto en pesos, el disponible solo sirve si viene en CLP (hay compras en UTM).
    monto = presupuesto.get("monto_disponible_clp")
    if monto is None and (presupuesto.get("moneda") or "CLP").strip().upper() == "CLP":
        monto = presupuesto.get("monto_disponible") or presupuesto.get("presupuesto_estimado")
    productos = ca.get("productos_solicitados") or []
    return {
        "CodigoExterno": ca.get("codigo"),
        "Nombre": ca.get("nombre"),
        "Descripcion": ca.get("descripcion"),
        "Estado": (ca.get("estado") or {}).get("glosa"),
        "MontoEstimado": monto,
        "Moneda": "CLP",
        "Tipo": TIPO,
        "Comprador": {
            "NombreOrganismo": institucion.get("organismo_comprador"),
            "NombreUnidad": institucion.get("unidad_compra"),
            "RegionUnidad": institucion.get("nombre_region")
            or (f"Región {institucion['region']}" if institucion.get("region") else None),
            "ComunaUnidad": None,
        },
        "Fechas": {"FechaCierre": fecha_chile(fechas.get("fecha_cierre")),
                   "FechaPublicacion": fecha_chile(fechas.get("fecha_publicacion"))},
        "Items": {"Listado": [{
            "Correlativo": n,
            "NombreProducto": p.get("nombre"),
            "Descripcion": p.get("descripcion"),
            "Categoria": None,
            "Cantidad": p.get("cantidad"),
            "UnidadMedida": p.get("unidad_medida"),
        } for n, p in enumerate(productos, 1)]},
        "Llamado": convocatoria.get("estado_convocatoria"),
        "PlazoEntregaDias": entrega.get("plazo_entrega_dias"),
        "DireccionEntrega": entrega.get("direccion_entrega"),
    }


def fila_compra_agil(det: dict, filtro: FiltroRubros, hoy: date | None = None) -> dict | None:
    """Fila con las columnas de licitaciones.json si pertenece a un rubro; si no, None."""
    fila = clasificar(det, filtro, hoy)
    if fila is None:
        return None
    return fila | {
        "url": URL_FICHA.format(requests.utils.quote(str(det.get("CodigoExterno")), safe="")),
        "llamado": det.get("Llamado"),
        "plazo_entrega_dias": det.get("PlazoEntregaDias"),
        "direccion_entrega": det.get("DireccionEntrega"),
    }


@dataclass
class ResultadoCompraAgil:
    filas: list[dict] = field(default_factory=list)
    detalles: dict[str, dict] = field(default_factory=dict)  # en forma de licitación
    publicadas: int = 0
    candidatas: int = 0
    fallidas: set[str] = field(default_factory=set)
    detenida: str | None = None                              # motivo si se cortó (cuota, tiempo)


def radar_compra_agil(cliente: ClienteCompraAgil, filtro: FiltroRubros, regiones: list[int] | None = None,
                      dias_publicacion: int = 15, tamano_pagina: int = 25, max_paginas: int = 200,
                      max_detalles: int = 400, hoy: date | None = None,
                      hasta_monotonic: float | None = None) -> ResultadoCompraAgil:
    """Compras Ágiles abiertas de tus rubros: listado → filtro por nombre → detalle → filtro completo."""
    resultado = ResultadoCompraAgil()
    # El listado usa a lo más la mitad del tiempo: el resto es para los detalles.
    mitad = (time.monotonic() + (hasta_monotonic - time.monotonic()) / 2) if hasta_monotonic is not None else None
    publicadas = listar_publicadas(cliente, regiones, dias_publicacion, tamano_pagina, max_paginas,
                                   hasta_monotonic=mitad)
    resultado.publicadas = len(publicadas)
    candidatas = [c for c in publicadas if filtro.es_candidata(c.get("nombre"))]
    # Las que cierran antes, primero: si se acaba la cuota, quedan las más urgentes.
    candidatas.sort(key=lambda c: str((c.get("fechas") or {}).get("fecha_cierre") or "9999"))
    resultado.candidatas = len(candidatas)
    log.info("Candidatas por nombre: %d de %d", len(candidatas), len(publicadas))
    for i, resumen in enumerate(candidatas, 1):
        codigo = resumen["codigo"]
        if i > max_detalles:
            resultado.detenida = f"máximo de {max_detalles} detalles"
            resultado.fallidas.update(c["codigo"] for c in candidatas[i - 1:])
            break
        if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
            resultado.detenida = "sin tiempo"
            resultado.fallidas.update(c["codigo"] for c in candidatas[i - 1:])
            break
        try:
            det = como_licitacion(cliente.detalle(codigo))
        except ErrorApi as e:
            if e.fatal:
                if e.temporal:   # 429: se guarda lo obtenido hasta ahora
                    resultado.detenida = str(e)
                    resultado.fallidas.update(c["codigo"] for c in candidatas[i - 1:])
                    break
                raise
            log.error("Sin detalle para %s: %s", codigo, e)
            resultado.fallidas.add(codigo)
            continue
        fila = fila_compra_agil(det, filtro, hoy)
        if fila:
            resultado.filas.append(fila)
            resultado.detalles[codigo] = det
        if i % 25 == 0:
            log.info("Detalle %d/%d", i, len(candidatas))
    log.info("Compras Ágiles en rubros: %d (sin revisar: %d)", len(resultado.filas), len(resultado.fallidas))
    return resultado
