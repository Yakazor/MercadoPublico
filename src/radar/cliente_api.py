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
    """Error definitivo de la API (no se resuelve reintentando)."""


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
                if resp.ok and not _es_error_temporal(datos):
                    if isinstance(datos, dict) and "Listado" not in datos and "Mensaje" in datos:
                        raise ErrorApi(f"{recurso} {visible}: {datos.get('Mensaje')}")
                    return datos
                if resp.status_code < 500 and resp.status_code != 429 and not _es_error_temporal(datos):
                    raise ErrorApi(
                        f"{recurso} {visible}: HTTP {resp.status_code} - {_mensaje(datos, resp)}"
                    )
                motivo = f"HTTP {resp.status_code} - {_mensaje(datos, resp)}"
            except (requests.ConnectionError, requests.Timeout) as e:
                self._ultima_llamada = time.monotonic()
                motivo = f"error de red: {e.__class__.__name__}"

            if intento == self.reintentos:
                raise ErrorApi(f"{recurso} {visible}: falló tras {self.reintentos} reintentos ({motivo})")
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


def _es_error_temporal(datos) -> bool:
    if not isinstance(datos, dict) or "Listado" in datos:
        return False
    msg = str(datos.get("Mensaje", "")).lower()
    return any(m in msg for m in _MENSAJES_TEMPORALES)
