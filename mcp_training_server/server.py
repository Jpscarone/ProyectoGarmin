from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

try:
    from .settings import get_settings
except ImportError:
    from settings import get_settings


SETTINGS = get_settings()

mcp = FastMCP(
    "Training MCP Server",
    host=SETTINGS.mcp_host,
    port=SETTINGS.mcp_port,
    streamable_http_path=SETTINGS.mcp_http_path,
    sse_path=SETTINGS.mcp_sse_path,
    message_path=SETTINGS.mcp_message_path,
    stateless_http=True,
    json_response=True,
)


def _validate_date(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ToolError("Usá formato dd/mm/aa, dd/mm/yyyy o YYYY-MM-DD")

    parsers = (
        lambda raw: date_type.fromisoformat(raw),
        lambda raw: datetime.strptime(raw, "%d/%m/%Y").date(),
        lambda raw: datetime.strptime(raw, "%d/%m/%y").date(),
    )
    for parser in parsers:
        try:
            return parser(normalized).isoformat()
        except ValueError:
            continue
    raise ToolError("Usá formato dd/mm/aa, dd/mm/yyyy o YYYY-MM-DD")


def _require_config() -> tuple[str, str]:
    api_url = SETTINGS.training_api_url
    api_token = SETTINGS.training_api_token

    if not api_url:
        raise ToolError("TRAINING_API_URL no esta configurado.")
    if not api_token:
        raise ToolError("TRAINING_API_TOKEN no esta configurado.")
    return api_url, api_token


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        detail = payload.get("detail")
        message = payload.get("message")
        error = payload.get("error")
        for candidate in (detail, message, error):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return f"HTTP {response.status_code}"


async def _get_json(path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
    api_url, api_token = _require_config()
    headers = {"Authorization": f"Bearer {api_token}"}
    request_params = dict(params or {})
    if SETTINGS.training_api_athlete_id is not None:
        request_params.setdefault("athlete_id", str(SETTINGS.training_api_athlete_id))

    try:
        async with httpx.AsyncClient(
            base_url=api_url,
            headers=headers,
            timeout=20.0,
        ) as client:
            response = await client.get(path, params=request_params or None)
    except httpx.RequestError as exc:
        raise ToolError(
            "No se pudo conectar al sistema de entrenamiento. Verifica que la API principal este disponible."
        ) from exc

    if response.status_code == 401:
        raise ToolError(
            "La API de entrenamiento rechazo la autenticacion. Revisa TRAINING_API_TOKEN."
        )
    if response.status_code == 404:
        detail = _extract_error_detail(response)
        raise ToolError(f"La API de entrenamiento devolvio 404: {detail}")
    if response.status_code >= 500:
        detail = _extract_error_detail(response)
        raise ToolError(f"La API de entrenamiento devolvio {response.status_code}: {detail}")
    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise ToolError(f"La API de entrenamiento devolvio {response.status_code}: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolError("La API de entrenamiento respondio con un payload no JSON.") from exc

    if not isinstance(payload, dict):
        raise ToolError("La API de entrenamiento respondio con un formato inesperado.")
    return payload


@mcp.tool()
async def get_session_feedback_by_date(date: str) -> dict[str, Any]:
    """Obtiene el feedback de una sesion para una fecha dd/mm/aa, dd/mm/yyyy o YYYY-MM-DD."""
    normalized_date = _validate_date(date)
    return await _get_json("/api/mcp/session-feedback", params={"date": normalized_date})


@mcp.tool()
async def get_week_context() -> dict[str, Any]:
    """Obtiene el contexto resumido de la semana actual."""
    return await _get_json("/api/mcp/week-context")


@mcp.tool()
async def get_last_activity_feedback() -> dict[str, Any]:
    """Obtiene feedback de la ultima actividad registrada."""
    return await _get_json("/api/mcp/last-activity-feedback")


@mcp.tool()
async def get_next_session_context() -> dict[str, Any]:
    """Obtiene contexto para decidir la proxima sesion."""
    return await _get_json("/api/mcp/next-session-context")


def main() -> None:
    transport = SETTINGS.mcp_transport
    if transport == "http":
        mcp.run(transport="streamable-http")
        return
    if transport == "sse":
        mcp.run(transport="sse")
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
