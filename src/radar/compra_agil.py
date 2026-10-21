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
VENTANA_LISTADO = timedelta(hours=1)
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
        self.hasta_monotonic: float | None = None   # la espera de un 429 no pasa de aquí

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

    def detalle(self, codigo: str, reintentos: int = 0) -> dict:
        """Sin reintentos por defecto: el detalle suele responder 504 por compras puntuales
        (~30 s cada intento); conviene pasar a la siguiente y volver en otra corrida."""
        return self._get(f"/v2/compra-agil/{requests.utils.quote(codigo, safe='')}", {}, reintentos)

    def _get(self, recurso: str, params: dict, reintentos: int | None = None) -> dict:
        reintentos = self.reintentos if reintentos is None else reintentos
        url = f"{self.base_url}{recurso}"
        consulta = {k: v for k, v in params.items() if v is not None}
        espera = self.espera_inicial
        intento = 0
        while True:
            # La pausa se cuenta desde el INICIO de la consulta anterior: una respuesta lenta
            # (~5 s por página) ya cumple el ritmo y no se le suma otra espera.
            transcurrido = time.monotonic() - self._ultima_llamada
            if transcurrido < self.pausa:
                time.sleep(self.pausa - transcurrido)
            self._ultima_llamada = time.monotonic()
            try:
                resp = self._sesion.get(url, params=consulta, headers={"ticket": self.ticket}, timeout=self.timeout)
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
                    con_tiempo = self.hasta_monotonic is None or time.monotonic() + pausa_429 < self.hasta_monotonic
                    if not self._esperado_429 and pausa_429 <= self.max_espera_429 and con_tiempo:
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
                motivo = f"error de red: {e.__class__.__name__}"
            if intento == reintentos:
                raise ErrorApi(f"{recurso}: falló tras {reintentos} reintentos ({motivo})", temporal=True)
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


def listar_publicadas(cliente: ClienteCompraAgil, desde: datetime, hasta: datetime, regiones: list[int] | None = None,
                      tamano_pagina: int = TAMANO_MINIMO, max_paginas: int = 400,
                      hasta_monotonic: float | None = None) -> tuple[list[dict], datetime]:
    """Compras Ágiles abiertas publicadas entre `desde` y `hasta` (hora de Chile: la API
    compara su hora de Chile marcada con "Z"), y hasta qué momento quedó completo el listado.

    Se recorre una hora de publicación a la vez (VENTANA_LISTADO), de la más antigua a la
    más nueva: un día de todo Chile son ~4.000 compras (~1 hora de API), así que solo una
    ventana corta alcanza a completarse y a hacer avanzar el listado. La API solo
    ordena de la más nueva a la más antigua, y si el listado se corta (tiempo o páginas)
    deben quedar las publicadas antes, que son las que cierran antes. Ventanas cortas
    también achican el corrimiento de filas mientras se pagina."""
    region = ",".join(str(r) for r in regiones) if regiones else None
    items, tamano, paginas_usadas, total_publicadas = [], tamano_pagina, 0, 0
    tope_filas = max_paginas * tamano_pagina   # no cambia si se achican las páginas
    cubierto = desde
    inicio = desde
    while inicio < hasta:
        fin = min(inicio + VENTANA_LISTADO - timedelta(seconds=1), hasta)
        params = {"estado": "publicada", "region": region, "ordenar_por": "FechaPublicacion",
                  "publicado_desde": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "publicado_hasta": fin.strftime("%Y-%m-%dT%H:%M:%SZ")}
        pagina = 1
        while True:
            if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
                log.warning("Sin tiempo: el listado quedó completo hasta %s.", cubierto)
                return _sin_repetidos(items), cubierto
            if paginas_usadas * tamano >= tope_filas:
                log.warning("Tope de %d páginas: el listado quedó completo hasta %s.", max_paginas, cubierto)
                return _sin_repetidos(items), cubierto
            try:
                payload = cliente.listado(**params, tamano_pagina=tamano, numero_pagina=pagina)
            except ErrorPaginaGrande:
                # Mismas filas con páginas de 10 (cambia la numeración).
                log.warning("HTTP 504 con páginas de %d: se sigue con páginas de %d.", tamano, TAMANO_MINIMO)
                pagina = (pagina - 1) * tamano // TAMANO_MINIMO + 1
                paginas_usadas = paginas_usadas * tamano // TAMANO_MINIMO
                tamano = TAMANO_MINIMO
                continue
            paginas_usadas += 1
            items += payload.get("items") or []
            paginacion = payload.get("paginacion") or {}
            if pagina == 1:
                total_publicadas += paginacion.get("total_resultados") or 0
            if pagina >= (paginacion.get("total_paginas") or 0):
                break
            pagina += 1
        cubierto = fin
        inicio = fin + timedelta(seconds=1)
    log.info("Compras Ágiles publicadas entre %s y %s (según la API): %d", desde, hasta, total_publicadas)
    return _sin_repetidos(items), cubierto


def _sin_repetidos(items: list[dict]) -> list[dict]:
    """Una compra puede repetirse si se movió de página mientras se recorría el listado."""
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


def _cierre(valor) -> datetime | None:
    texto = fecha_chile(valor)
    try:
        return datetime.fromisoformat(texto) if texto else None
    except ValueError:
        return None


MAX_INTENTOS_DETALLE = 3     # corridas en que se intenta el detalle de una compra
MAX_FALLAS_SEGUIDAS = 15     # detalles seguidos sin respuesta: la API está caída, se sigue en la próxima


def _pendiente(valor) -> dict:
    """Pendiente guardada como texto (formato anterior: solo el cierre) → dict."""
    if isinstance(valor, dict):
        return {"cierre": valor.get("cierre"), "intentos": valor.get("intentos", 0), "prioridad": valor.get("prioridad", 1)}
    return {"cierre": valor, "intentos": 0, "prioridad": 1}


def estado_vacio() -> dict:
    """Memoria entre corridas (se guarda en la caché de GitHub Actions).

    - listado_hasta: hasta qué hora de publicación ya se listó (hora de Chile);
    - abiertas: {codigo: {"fila", "detalle"}} de tus rubros;
    - descartadas: {codigo: cierre} revisadas que no son de tus rubros;
    - pendientes: {codigo: {"cierre", "intentos", "prioridad"}} candidatas por nombre a las
      que falta pedir el detalle (prioridad 0 = el nombre solo ya calza con un rubro)."""
    return {"version": 1, "listado_hasta": None, "abiertas": {}, "descartadas": {}, "pendientes": {}}


@dataclass
class ResultadoCompraAgil:
    listadas: int = 0
    nuevas_candidatas: int = 0
    detalles: int = 0
    nuevas_en_rubros: int = 0
    pendientes: int = 0
    detenida: str | None = None                              # motivo si se cortó (cuota, tiempo)


def actualizar_compras_agiles(cliente: ClienteCompraAgil, filtro: FiltroRubros, estado: dict,
                              regiones: list[int] | None = None, dias_iniciales: int = 3,
                              tamano_pagina: int = TAMANO_MINIMO, max_paginas: int = 400,
                              max_detalles: int = 700, ahora: datetime | None = None,
                              hasta_monotonic: float | None = None) -> ResultadoCompraAgil:
    """Suma al `estado` las Compras Ágiles publicadas desde la corrida anterior.

    listado (solo lo nuevo) → filtro por nombre → detalle de las candidatas (primero las
    que cierran antes) → filtro completo. Se quitan las que ya cerraron. Lo que no alcanza
    a revisarse queda pendiente para la próxima corrida."""
    ahora = ahora or ahora_chile()
    hoy = ahora.date()
    r = ResultadoCompraAgil()
    cliente.hasta_monotonic = hasta_monotonic
    anterior = _cierre(estado.get("listado_hasta"))
    # Una hora de margen: compras publicadas justo al final del listado anterior.
    desde = max(anterior - timedelta(hours=1), ahora - timedelta(days=dias_iniciales)) if anterior \
        else ahora - timedelta(days=dias_iniciales)
    # El listado usa a lo más 60 % del tiempo: el resto es para los detalles.
    limite_listado = (time.monotonic() + (hasta_monotonic - time.monotonic()) * 0.6) if hasta_monotonic else None
    try:
        listadas, cubierto = listar_publicadas(cliente, desde, ahora, regiones, tamano_pagina, max_paginas,
                                               hasta_monotonic=limite_listado)
    except ErrorApi as e:
        if not (e.fatal and e.temporal):
            raise
        listadas, cubierto, r.detenida = [], desde, str(e)   # 429: se siguen los detalles pendientes
    r.listadas = len(listadas)
    estado["pendientes"] = {k: _pendiente(v) for k, v in estado["pendientes"].items()}
    conocidas = estado["abiertas"].keys() | estado["descartadas"].keys() | estado["pendientes"].keys()
    for c in listadas:
        nombre = c.get("nombre")
        if c.get("codigo") not in conocidas and filtro.es_candidata(nombre):
            estado["pendientes"][c["codigo"]] = {
                "cierre": (c.get("fechas") or {}).get("fecha_cierre"), "intentos": 0,
                # Las que ya calzan solo por el nombre ("Compra de guantes de nitrilo") van
                # antes que las que solo lo sugieren ("Compra de insumos").
                "prioridad": 0 if filtro.evaluar(nombre=nombre).coincide else 1}
            r.nuevas_candidatas += 1
    if cubierto > (anterior or desde):
        estado["listado_hasta"] = cubierto.isoformat(timespec="seconds")

    # Las que ya cerraron salen de la memoria.
    # Las pendientes que cierran en menos de una hora ya no alcanzan a cotizarse.
    estado["pendientes"] = {k: v for k, v in estado["pendientes"].items()
                            if not ((c := _cierre(v["cierre"])) and c < ahora + timedelta(hours=1))}
    estado["descartadas"] = {k: v for k, v in estado["descartadas"].items() if not ((c := _cierre(v)) and c < ahora)}
    estado["abiertas"] = {k: v for k, v in estado["abiertas"].items()
                          if not ((c := _cierre((v.get("fila") or {}).get("fecha_cierre"))) and c < ahora)}
    # Se reclasifican con la config.yaml vigente (sin llamar a la API): un cambio en los
    # rubros o exclusiones se aplica también a las que ya estaban guardadas.
    for codigo, abierta in list(estado["abiertas"].items()):
        fila = fila_compra_agil(abierta["detalle"], filtro, hoy)
        if fila:
            abierta["fila"] = fila
        else:
            estado["descartadas"][codigo] = abierta["fila"].get("fecha_cierre")
            del estado["abiertas"][codigo]

    pendientes = sorted(estado["pendientes"].items(),
                        key=lambda kv: (kv[1]["prioridad"], str(_cierre(kv[1]["cierre"]) or "9999")))
    fallas_seguidas = 0
    for codigo, pendiente in pendientes:
        cierre = pendiente["cierre"]
        if fallas_seguidas >= MAX_FALLAS_SEGUIDAS:
            r.detenida = f"{fallas_seguidas} detalles seguidos sin respuesta (la API está lenta)"
            break
        if r.detenida:
            break
        if r.detalles >= max_detalles:
            r.detenida = f"máximo de {max_detalles} detalles"
            break
        if hasta_monotonic is not None and time.monotonic() > hasta_monotonic:
            r.detenida = "sin tiempo"
            break
        try:
            det = como_licitacion(cliente.detalle(codigo))
        except ErrorApi as e:
            if e.fatal:
                if e.temporal:   # 429 repetido: lo demás queda pendiente
                    r.detenida = str(e)
                    break
                raise
            pendiente["intentos"] += 1
            fallas_seguidas += 1
            # 404 u otro error definitivo, o varias corridas sin respuesta: no se insiste.
            if not e.temporal or pendiente["intentos"] >= MAX_INTENTOS_DETALLE:
                log.warning("Sin detalle para %s (%d intentos): %s", codigo, pendiente["intentos"], e)
                estado["pendientes"].pop(codigo, None)
                estado["descartadas"][codigo] = cierre
            continue
        fallas_seguidas = 0
        r.detalles += 1
        estado["pendientes"].pop(codigo, None)
        fila = fila_compra_agil(det, filtro, hoy)
        if fila:
            estado["abiertas"][codigo] = {"fila": fila, "detalle": det}
            r.nuevas_en_rubros += 1
        else:
            estado["descartadas"][codigo] = cierre or det["Fechas"].get("FechaCierre")
        if r.detalles % 50 == 0:
            log.info("Detalle %d/%d", r.detalles, len(pendientes))
    r.pendientes = len(estado["pendientes"])
    log.info("Compras Ágiles: %d listadas, %d candidatas nuevas, %d detalles, %d nuevas en tus rubros, "
             "%d abiertas en tus rubros, %d pendientes%s", r.listadas, r.nuevas_candidatas, r.detalles,
             r.nuevas_en_rubros, len(estado["abiertas"]), r.pendientes, f" ({r.detenida})" if r.detenida else "")
    return r
