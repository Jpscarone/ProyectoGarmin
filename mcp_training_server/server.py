from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    from .client import TrainingAppApiClient
    from .settings import get_settings
except ImportError:
    from client import TrainingAppApiClient
    from settings import get_settings


SETTINGS = get_settings()
CLIENT = TrainingAppApiClient(SETTINGS)

mcp = FastMCP(
    "ProyectoGarmin MCP Server",
    host=SETTINGS.mcp_host,
    port=SETTINGS.mcp_port,
    streamable_http_path=SETTINGS.mcp_http_path,
    sse_path=SETTINGS.mcp_sse_path,
    message_path=SETTINGS.mcp_message_path,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
async def get_athletes() -> dict[str, Any] | list[dict[str, Any]]:
    """Devuelve los atletas disponibles."""
    return await CLIENT.get_athletes()


@mcp.tool()
async def get_recent_activities(athlete_id: int, limit: int = 10) -> dict[str, Any]:
    """Devuelve las actividades recientes de un atleta."""
    return await CLIENT.get_recent_activities(athlete_id=athlete_id, limit=limit)


@mcp.tool()
async def get_activity_detail(athlete_id: int, activity_id: int) -> dict[str, Any]:
    """Devuelve el detalle de una actividad y cualquier analisis asociado."""
    return await CLIENT.get_activity_detail(athlete_id=athlete_id, activity_id=activity_id)


@mcp.tool()
async def get_health_summary(athlete_id: int) -> dict[str, Any]:
    """Devuelve el resumen de salud/readiness de un atleta."""
    return await CLIENT.get_health_summary(athlete_id=athlete_id)


@mcp.tool()
async def get_latest_weekly_analysis(athlete_id: int) -> dict[str, Any]:
    """Devuelve el ultimo analisis semanal guardado para un atleta."""
    return await CLIENT.get_latest_weekly_analysis(athlete_id=athlete_id)


@mcp.tool()
async def get_training_status(athlete_id: int) -> dict[str, Any]:
    """Devuelve el estado general del atleta, plan, salud y actividad reciente."""
    return await CLIENT.get_training_status(athlete_id=athlete_id)


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
