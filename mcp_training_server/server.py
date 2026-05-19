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


@mcp.tool()
async def identify_me(access_code: str) -> dict[str, Any]:
    """Identifica al atleta asociado a una clave privada experimental, sin exponer athlete_id en la consulta."""
    return await CLIENT.identify_me(access_code=access_code)


@mcp.tool()
async def get_my_recent_activities(access_code: str, limit: int = 10) -> dict[str, Any]:
    """Devuelve las actividades recientes del atleta asociado a la clave privada indicada."""
    return await CLIENT.get_my_recent_activities(access_code=access_code, limit=limit)


@mcp.tool()
async def get_my_health_summary(access_code: str) -> dict[str, Any]:
    """Devuelve el resumen de salud/readiness del atleta asociado a la clave privada indicada."""
    return await CLIENT.get_my_health_summary(access_code=access_code)


@mcp.tool()
async def get_my_training_status(access_code: str) -> dict[str, Any]:
    """Devuelve el estado general del atleta asociado a la clave privada indicada."""
    return await CLIENT.get_my_training_status(access_code=access_code)


@mcp.tool()
async def get_day_overview(athlete_id: int, date: str) -> dict[str, Any]:
    """Devuelve el panorama completo del dia exacto: planificacion, actividades y matches si existen."""
    return await CLIENT.get_day_overview(athlete_id=athlete_id, date=date)


@mcp.tool()
async def get_my_day_overview(access_code: str, date: str) -> dict[str, Any]:
    """Devuelve el panorama completo del dia exacto solo para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_day_overview(access_code=access_code, date=date)


@mcp.tool()
async def compare_planned_vs_done(
    athlete_id: int,
    date: str | None = None,
    activity_id: int | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Compara una sesion programada contra la actividad realizada, sin modificar datos."""
    return await CLIENT.compare_planned_vs_done(
        athlete_id=athlete_id,
        date=date,
        activity_id=activity_id,
        planned_session_id=planned_session_id,
    )


@mcp.tool()
async def compare_my_planned_vs_done(
    access_code: str,
    date: str | None = None,
) -> dict[str, Any]:
    """Compara lo planificado vs lo realizado solo para el atleta resuelto por la clave privada indicada."""
    return await CLIENT.compare_my_planned_vs_done(
        access_code=access_code,
        date=date,
    )


@mcp.tool()
async def get_next_session_recommendation(
    athlete_id: int,
    reference_date: str | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Devuelve una recomendacion read-only para la proxima sesion segun estado actual."""
    return await CLIENT.get_next_session_recommendation(
        athlete_id=athlete_id,
        reference_date=reference_date,
        planned_session_id=planned_session_id,
    )


@mcp.tool()
async def get_my_next_session_recommendation(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve una recomendacion read-only para la proxima sesion del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_next_session_recommendation(
        access_code=access_code,
        reference_date=reference_date,
    )


@mcp.tool()
async def get_week_load_summary(
    athlete_id: int,
    week_start_date: str | None = None,
    compare_previous: bool = True,
) -> dict[str, Any]:
    """Devuelve un resumen read-only de carga semanal, opcionalmente comparado con la semana previa."""
    return await CLIENT.get_week_load_summary(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
        compare_previous=compare_previous,
    )


@mcp.tool()
async def get_my_week_load_summary(
    access_code: str,
    week_start_date: str | None = None,
    compare_previous: bool = True,
) -> dict[str, Any]:
    """Devuelve un resumen read-only de carga semanal para el atleta resuelto por la clave privada."""
    return await CLIENT.get_my_week_load_summary(
        access_code=access_code,
        week_start_date=week_start_date,
        compare_previous=compare_previous,
    )


@mcp.tool()
async def get_session_analysis_payload(
    athlete_id: int,
    planned_session_id: int | None = None,
    activity_id: int | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Devuelve el payload tecnico del analisis de sesion para evitar copiado manual desde la web."""
    return await CLIENT.get_session_analysis_payload(
        athlete_id=athlete_id,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date=date,
    )


@mcp.tool()
async def get_my_session_analysis_payload(
    access_code: str,
    date: str | None = None,
    activity_id: int | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Devuelve el payload tecnico de analisis de sesion solo para el atleta resuelto por la clave privada."""
    return await CLIENT.get_my_session_analysis_payload(
        access_code=access_code,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date=date,
    )


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
