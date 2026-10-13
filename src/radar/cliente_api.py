"""Cliente HTTP de la API de Mercado Público.

- El ticket se lee desde .env (MP_TICKET), nunca se escribe en el código.
- Pausa fija entre llamadas para respetar el límite de la API.
- Reintentos con espera creciente ante errores temporales (5xx, 429,
  "peticiones simultáneas", cortes de red).
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

URL_BASE = "https://api.mercadopublico.cl/servicios/v1/publico"

# Mensajes con que la API indica que hay que esperar y reintentar.
_MENSAJES_TEMPORALES = ("simultane", "intente nuevamente", "limite")


class ErrorApi(Exception):
    """Error de la API.

    `temporal=True`: se agotaron los reintentos (5xx, 429, red, respuesta sin JSON);
    puede funcionar más tarde. `temporal=False`: error definitivo (p. ej. código
    inválido): reintentar no sirve. `fatal=True`: afecta a toda la ejecución (ticket
    rechazado, HTTP 401/403): hay que detenerse sin marcar nada como procesado."""

    def __init__(self, mensaje: str, temporal: bool = False, fatal: bool = False):
        super().__init__(mensaje)
        self.temporal = temporal
        self.fatal = fatal


class ClienteMercadoPublico:
    def __init__(
        self,
        ticket: str,
        base_url: str = URL_BASE,
        timeout: float = 30,
        pausa: float = 2.0,
        reintentos: int = 4,
        espera_inicial: float = 2.0,
    ):
        self.ticket = ticket
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pausa = pausa
        self.reintentos = reintentos
        self.espera_inicial = espera_inicial
        self._sesion = requests.Session()
        self._ultima_llamada = 0.0

    @classmethod
    def desde_config(cls, config: dict, ticket: str) -> "ClienteMercadoPublico":
        api = config.get("api", {})
        return cls(
            ticket=ticket,
            base_url=api.get("base_url", URL_BASE),
            timeout=api.get("timeout_segundos", 30),
            pausa=api.get("pausa_entre_llamadas_segundos", 2.0),
            reintentos=api.get("reintentos", 4),
            espera_inicial=api.get("espera_inicial_reintento_segundos", 2.0),
        )

    # -- API pública ---------------------------------------------------
    def licitaciones(self, **params) -> dict:
        """GET licitaciones.json. Params: estado, fecha (ddmmaaaa), codigo."""
        return self._get("licitaciones.json", params)

    def ordenes_de_compra(self, **params) -> dict:
        """GET ordenesdecompra.json. Params: estado, fecha (ddmmaaaa), codigo."""
        return self._get("ordenesdecompra.json", params)

    # -- Interno -------------------------------------------------------
    def _esperar_turno(self) -> None:
        transcurrido = time.monotonic() - self._ultima_llamada
        if transcurrido < self.pausa:
            time.sleep(self.pausa - transcurrido)

    def _get(self, recurso: str, params: dict) -> dict:
        url = f"{self.base_url}/{recurso}"
        consulta = {k: v for k, v in params.items() if v is not None}
        consulta["ticket"] = self.ticket
        visible = {k: v for k, v in consulta.items() if k != "ticket"}

        espera = self.espera_inicial
        for intento in range(self.reintentos + 1):
            self._esperar_turno()
            try:
                resp = self._sesion.get(url, params=consulta, timeout=self.timeout)
                self._ultima_llamada = time.monotonic()
                datos = _leer_json(resp)
                if resp.ok and not isinstance(datos, dict):
                    # 200 con HTML/vacío (p. ej. página de mantenimiento): temporal.
                    motivo = f"HTTP {resp.status_code} sin JSON válido"
                elif resp.ok and not _es_error_temporal(datos):
                    if "Listado" not in datos and "Mensaje" in datos:
                        mensaje = str(datos.get("Mensaje"))
                        raise ErrorApi(f"{recurso} {visible}: {mensaje}", fatal=_es_fatal(resp.status_code, mensaje))
                    return datos
                elif resp.status_code < 500 and resp.status_code != 429 and not _es_error_temporal(datos):
                    mensaje = _mensaje(datos, resp)
                    raise ErrorApi(f"{recurso} {visible}: HTTP {resp.status_code} - {mensaje}",
                                   fatal=_es_fatal(resp.status_code, mensaje))
                elif isinstance(datos, dict) and "ticket" in str(datos.get("Mensaje", "")).lower():
                    # Ticket rechazado aunque venga como 5xx: reintentar no sirve.
                    raise ErrorApi(f"{recurso} {visible}: HTTP {resp.status_code} - {datos.get('Mensaje')}",
                                   fatal=True)
                else:
                    motivo = f"HTTP {resp.status_code} - {_mensaje(datos, resp)}"
            except requests.RequestException as e:
                # Red, timeout o conexión cortada a mitad de la respuesta.
                self._ultima_llamada = time.monotonic()
                motivo = f"error de red: {e.__class__.__name__}"

            if intento == self.reintentos:
                raise ErrorApi(f"{recurso} {visible}: falló tras {self.reintentos} reintentos ({motivo})",
                               temporal=True)
            log.warning("%s %s: %s. Reintento en %.0f s", recurso, visible, motivo, espera)
            time.sleep(espera)
            espera *= 2
        raise AssertionError("inalcanzable")


def _leer_json(resp: requests.Response):
    try:
        return resp.json()
    except ValueError:
        return None


def _mensaje(datos, resp: requests.Response) -> str:
    if isinstance(datos, dict) and datos.get("Mensaje"):
        return str(datos["Mensaje"])
    return resp.text[:200]


def _es_fatal(status: int, mensaje: str) -> bool:
    """Ticket inválido o acceso denegado: ninguna otra llamada va a funcionar."""
    return status in (401, 403) or "ticket" in mensaje.lower()


def _es_error_temporal(datos) -> bool:
    if not isinstance(datos, dict) or "Listado" in datos:
        return False
    msg = str(datos.get("Mensaje", "")).lower()
    return any(m in msg for m in _MENSAJES_TEMPORALES)
