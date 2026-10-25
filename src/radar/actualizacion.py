"""Actualizar los datos desde la plataforma: pide a GitHub Actions las corridas que consultan
la API de Mercado Público y muestra en qué van.

Los workflows corren en GitHub, no en la plataforma: aquí solo se lanzan (workflow_dispatch)
con un token de GitHub con permiso «Actions: Read and write» sobre el repositorio. Ver las
corridas no necesita token (el repositorio es público), pero sin él GitHub permite pocas
consultas por hora.

- `corridas(token)`: últimas corridas de la rama principal, de la más nueva a la más antigua.
- `actualizar(token, corridas)`: lanza «Compras Ágiles» y «Radar diario» salvo que ya estén
  corriendo o en cola. El radar comparte la base con «Órdenes de compra históricas» (mismo
  grupo de concurrencia): si una de las dos está en cola, una corrida nueva la cancelaría.
  Las corridas «solo exportar» del radar (las lanza «Compras Ágiles» para publicar, sin
  consultar la API) no cuentan: un radar completo publica lo mismo y más.
"""
from __future__ import annotations

from datetime import datetime

import requests

API = "https://api.github.com"
REPO = "Yakazor/MercadoPublico"
RAMA = "feature/api-mercadopublico"
WORKFLOWS = {
    "radar-diario.yml": "Licitaciones (radar diario)",
    "compra-agil.yml": "Compras Ágiles",
    "ordenes-historicas.yml": "Precios de órdenes de compra",
    "informes.yml": "Verificar precios e informes PDF",
}
GRUPO_BASE = ("radar-diario.yml", "ordenes-historicas.yml")
EN_COLA = {"queued", "pending", "waiting", "requested"}
SOLO_EXPORTAR = "Publicar datos (solo exportar)"   # run-name de radar-diario.yml en ese modo


class ErrorGitHub(Exception):
    pass


def _cabeceras(token: str | None) -> dict:
    cabeceras = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    return cabeceras


def _error(r: requests.Response) -> ErrorGitHub:
    if r.status_code == 401:
        return ErrorGitHub("GitHub rechazó el token (vencido o mal copiado).")
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        return ErrorGitHub("GitHub limitó las consultas por esta hora; agrega un token para tener más.")
    if r.status_code in (403, 404):
        return ErrorGitHub("El token no tiene permiso «Actions: Read and write» sobre el repositorio "
                           f"(HTTP {r.status_code}).")
    try:
        detalle = r.json().get("message", "")
    except ValueError:
        detalle = r.text[:200]
    return ErrorGitHub(f"GitHub respondió HTTP {r.status_code}: {detalle}")


def _fecha(texto: str | None) -> datetime | None:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")) if texto else None


def corridas(token: str | None = None, repo: str = REPO, rama: str = RAMA, cantidad: int = 30,
             timeout: float = 20) -> list[dict]:
    r = requests.get(f"{API}/repos/{repo}/actions/runs", params={"branch": rama, "per_page": cantidad},
                     headers=_cabeceras(token), timeout=timeout)
    if r.status_code != 200:
        raise _error(r)
    filas = []
    for run in r.json().get("workflow_runs", []):
        archivo = (run.get("path") or "").split("/")[-1].split("@")[0]
        terminada = run.get("status") == "completed"
        exportar = archivo == "radar-diario.yml" and run.get("display_title") == SOLO_EXPORTAR
        filas.append({
            "id": run.get("id"), "workflow": archivo, "solo_exportar": exportar,
            "nombre": "Publicar datos (sin consultar la API)" if exportar else WORKFLOWS.get(archivo, run.get("name")),
            "estado": "en_cola" if run.get("status") in EN_COLA else run.get("status"),
            "resultado": run.get("conclusion"), "evento": run.get("event"),
            "inicio": _fecha(run.get("run_started_at") or run.get("created_at")),
            "fin": _fecha(run.get("updated_at")) if terminada else None, "url": run.get("html_url"),
        })
    return filas


def lanzar(workflow: str, token: str, repo: str = REPO, rama: str = RAMA, inputs: dict | None = None,
           timeout: float = 20) -> None:
    if workflow not in WORKFLOWS:
        raise ValueError(f"Workflow desconocido: {workflow}")
    if not token:
        raise ErrorGitHub("Falta el token de GitHub (secreto github_token).")
    r = requests.post(f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches",
                      json={"ref": rama, "inputs": inputs or {}}, headers=_cabeceras(token), timeout=timeout)
    if r.status_code not in (200, 204):
        raise _error(r)


def motivo_para_no_lanzar(workflow: str, actuales: list[dict]) -> str | None:
    """Por qué no conviene lanzar `workflow` ahora (None si se puede). Las corridas «solo
    exportar» no impiden lanzar el radar: si la nueva la cancela, el radar publica lo mismo."""
    activas = [c for c in actuales if not c.get("solo_exportar")]
    if any(c["workflow"] == workflow and c["estado"] in ("en_cola", "in_progress") for c in activas):
        return "ya está corriendo o en cola"
    if workflow in GRUPO_BASE and any(c["workflow"] in GRUPO_BASE and c["estado"] == "en_cola" for c in activas):
        return "hay otra corrida que usa la misma base esperando turno"
    return None


def actualizar(token: str, actuales: list[dict], repo: str = REPO, rama: str = RAMA) -> list[tuple[str, str]]:
    """Lanza Compras Ágiles y el radar. Devuelve (workflow, «lanzado» o el motivo para no lanzarlo)."""
    resultado = []
    for workflow in ("compra-agil.yml", "radar-diario.yml"):
        motivo = motivo_para_no_lanzar(workflow, actuales)
        if motivo is None:
            lanzar(workflow, token, repo, rama)
        resultado.append((workflow, motivo or "lanzado"))
    return resultado
