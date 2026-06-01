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

PUBLIC_MCP_TOOL_NAMES: tuple[str, ...] = (
    "get_athletes",
    "get_recent_activities",
    "get_health_summary",
    "get_week_plan",
    "get_my_week_plan",
    "get_day_plan",
    "get_remaining_week_plan",
    "get_today_remaining_sessions",
    "get_next_planned_session",
    "get_today_coach_briefing",
    "get_my_today_coach_briefing",
    "get_training_dashboard",
    "get_fatigue_risk_summary",
    "get_my_health_summary",
    "get_session_metrics_json",
    "get_my_session_metrics_json",
    "get_week_metrics_json",
    "get_my_week_metrics_json",
    "preview_plan_import",
    "verify_plan_import",
    "commit_plan_import",
    "get_next_session_decision",
    "get_plan_adjustment_suggestions",
    "generate_plan_adjustment_import_text",
)


async def get_athletes() -> dict[str, Any] | list[dict[str, Any]]:
    """Devuelve los atletas disponibles."""
    return await CLIENT.get_athletes()


async def get_recent_activities(athlete_id: int, limit: int = 10) -> dict[str, Any]:
    """Devuelve las actividades recientes de un atleta."""
    return await CLIENT.get_recent_activities(athlete_id=athlete_id, limit=limit)


async def get_activity_detail(athlete_id: int, activity_id: int) -> dict[str, Any]:
    """Devuelve el detalle de una actividad y cualquier analisis asociado."""
    return await CLIENT.get_activity_detail(athlete_id=athlete_id, activity_id=activity_id)


async def get_health_summary(athlete_id: int) -> dict[str, Any]:
    """Devuelve el resumen de salud/readiness de un atleta."""
    return await CLIENT.get_health_summary(athlete_id=athlete_id)


async def get_latest_weekly_analysis(athlete_id: int) -> dict[str, Any]:
    """Devuelve el ultimo analisis semanal guardado para un atleta."""
    return await CLIENT.get_latest_weekly_analysis(athlete_id=athlete_id)


async def get_week_metrics_json(
    athlete_id: int,
    week_start_date: str | None = None,
    week_end_date: str | None = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve el weekly metrics_json completo como fuente principal para analisis conversacional semanal."""
    return await CLIENT.get_week_metrics_json(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
        reference_date=reference_date,
    )


async def get_training_status(athlete_id: int) -> dict[str, Any]:
    """Devuelve el estado general del atleta, plan, salud y actividad reciente."""
    return await CLIENT.get_training_status(athlete_id=athlete_id)


async def get_day_plan(athlete_id: int, date: str) -> dict[str, Any]:
    """Devuelve la planificacion exacta de una fecha: training_day, sesiones y actividad vinculada si existe."""
    return await CLIENT.get_day_plan(athlete_id=athlete_id, date=date)


async def get_week_plan(
    athlete_id: int,
    week_start_date: str | None = None,
    include_completed: bool = True,
) -> dict[str, Any]:
    """Devuelve la planificacion semanal exacta sin reemplazar por actividades Garmin cercanas."""
    return await CLIENT.get_week_plan(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
        include_completed=include_completed,
    )


async def identify_me(access_code: str) -> dict[str, Any]:
    """Identifica al atleta asociado a una clave privada experimental, sin exponer athlete_id en la consulta."""
    return await CLIENT.identify_me(access_code=access_code)


async def get_my_recent_activities(access_code: str, limit: int = 10) -> dict[str, Any]:
    """Devuelve solo actividades Garmin recientes del atleta. No incluye sesiones de gimnasio/fuerza completadas manualmente."""
    return await CLIENT.get_my_recent_activities(access_code=access_code, limit=limit)


async def get_my_health_summary(access_code: str) -> dict[str, Any]:
    """Devuelve el resumen de salud/readiness del atleta asociado a la clave privada indicada."""
    return await CLIENT.get_my_health_summary(access_code=access_code)


async def get_my_training_status(access_code: str) -> dict[str, Any]:
    """Devuelve el estado general del atleta asociado a la clave privada indicada."""
    return await CLIENT.get_my_training_status(access_code=access_code)


async def get_my_week_metrics_json(
    access_code: str,
    week_start_date: str | None = None,
    week_end_date: str | None = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve el weekly metrics_json completo solo para el atleta resuelto por la clave privada."""
    return await CLIENT.get_my_week_metrics_json(
        access_code=access_code,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
        reference_date=reference_date,
    )


async def get_my_day_plan(access_code: str, date: str) -> dict[str, Any]:
    """Devuelve la planificacion exacta del dia solo para el atleta resuelto por la clave privada."""
    return await CLIENT.get_my_day_plan(access_code=access_code, date=date)


async def get_my_week_plan(
    access_code: str,
    week_start_date: str | None = None,
    include_completed: bool = True,
) -> dict[str, Any]:
    """Devuelve la planificacion semanal exacta del atleta resuelto por la clave privada indicada."""
    return await CLIENT.get_my_week_plan(
        access_code=access_code,
        week_start_date=week_start_date,
        include_completed=include_completed,
    )


async def get_day_overview(athlete_id: int, date: str) -> dict[str, Any]:
    """Devuelve el panorama completo del dia exacto: planificacion, actividades y matches si existen."""
    return await CLIENT.get_day_overview(athlete_id=athlete_id, date=date)


async def get_my_day_overview(access_code: str, date: str) -> dict[str, Any]:
    """Devuelve el panorama completo del dia exacto solo para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_day_overview(access_code=access_code, date=date)


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


async def compare_my_planned_vs_done(
    access_code: str,
    date: str | None = None,
) -> dict[str, Any]:
    """Compara lo planificado vs lo realizado solo para el atleta resuelto por la clave privada indicada."""
    return await CLIENT.compare_my_planned_vs_done(
        access_code=access_code,
        date=date,
    )


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


async def get_my_next_session_recommendation(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve una recomendacion read-only para la proxima sesion del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_next_session_recommendation(
        access_code=access_code,
        reference_date=reference_date,
    )


async def get_week_load_summary(
    athlete_id: int,
    week_start_date: str | None = None,
    compare_previous: bool = True,
) -> dict[str, Any]:
    """Devuelve un resumen semanal read-only que incluye actividades Garmin y sesiones manuales/completadas de gimnasio-fuerza sin duplicar matches. Usar para preguntas tipo cuantas sesiones hice en la semana."""
    return await CLIENT.get_week_load_summary(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
        compare_previous=compare_previous,
    )


async def get_my_week_load_summary(
    access_code: str,
    week_start_date: str | None = None,
    compare_previous: bool = True,
) -> dict[str, Any]:
    """Devuelve un resumen semanal read-only del atleta resuelto por la clave privada. Incluye actividades Garmin y sesiones manuales/completadas de gimnasio-fuerza sin duplicar matches. Esta es la tool correcta para preguntas semanales de gym/fuerza."""
    return await CLIENT.get_my_week_load_summary(
        access_code=access_code,
        week_start_date=week_start_date,
        compare_previous=compare_previous,
    )


async def get_remaining_week_plan(
    athlete_id: int,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve lo que todavia queda pendiente en la semana actual o consultada, separado entre exigible y opcional."""
    return await CLIENT.get_remaining_week_plan(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
    )


async def get_my_remaining_week_plan(
    access_code: str,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve lo que queda pendiente en la semana para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_remaining_week_plan(
        access_code=access_code,
        week_start_date=week_start_date,
    )


async def get_previous_week_summary(athlete_id: int) -> dict[str, Any]:
    """Devuelve un resumen simple, deterministico y read-only de lo realizado la semana pasada."""
    return await CLIENT.get_previous_week_summary(athlete_id=athlete_id)


async def get_my_previous_week_summary(access_code: str) -> dict[str, Any]:
    """Devuelve el resumen de la semana pasada solo para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_previous_week_summary(access_code=access_code)


async def get_next_planned_session(
    athlete_id: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve la proxima sesion pendiente, ignorando canceladas y completadas."""
    return await CLIENT.get_next_planned_session(
        athlete_id=athlete_id,
        reference_date=reference_date,
    )


async def get_my_next_planned_session(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve la proxima sesion pendiente del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_next_planned_session(
        access_code=access_code,
        reference_date=reference_date,
    )


async def get_today_remaining_sessions(athlete_id: int) -> dict[str, Any]:
    """Devuelve solo las sesiones pendientes de hoy, sin incluir canceladas ni completadas."""
    return await CLIENT.get_today_remaining_sessions(athlete_id=athlete_id)


async def get_my_today_remaining_sessions(access_code: str) -> dict[str, Any]:
    """Devuelve las sesiones pendientes de hoy solo para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_today_remaining_sessions(access_code=access_code)


async def get_week_adherence(
    athlete_id: int,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve cumplimiento semanal read-only usando la formula completed / (planned - cancelled)."""
    return await CLIENT.get_week_adherence(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
    )


async def get_today_coach_briefing(
    athlete_id: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compone un briefing diario read-only con readiness, sesiones de hoy, riesgo y foco recomendado."""
    return await CLIENT.get_today_coach_briefing(
        athlete_id=athlete_id,
        reference_date=reference_date,
    )


async def get_my_week_adherence(
    access_code: str,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve el cumplimiento semanal del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_week_adherence(
        access_code=access_code,
        week_start_date=week_start_date,
    )


async def get_my_today_coach_briefing(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compone el briefing diario del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_today_coach_briefing(
        access_code=access_code,
        reference_date=reference_date,
    )


async def get_week_comparison(
    athlete_id: int,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve una comparacion deterministica entre la semana actual o consultada y la semana previa."""
    return await CLIENT.get_week_comparison(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
    )


async def get_my_week_comparison(
    access_code: str,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve la comparacion semanal para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_week_comparison(
        access_code=access_code,
        week_start_date=week_start_date,
    )


async def get_training_load_trend(
    athlete_id: int,
    weeks: int = 4,
) -> dict[str, Any]:
    """Devuelve la tendencia reciente de carga semanal usando datos reales y duracion como proxy si hace falta."""
    return await CLIENT.get_training_load_trend(
        athlete_id=athlete_id,
        weeks=weeks,
    )


async def get_my_training_load_trend(
    access_code: str,
    weeks: int = 4,
) -> dict[str, Any]:
    """Devuelve la tendencia de carga del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_training_load_trend(
        access_code=access_code,
        weeks=weeks,
    )


async def get_fatigue_risk_summary(
    athlete_id: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve un resumen deterministico de riesgo de fatiga segun salud disponible y carga reciente."""
    return await CLIENT.get_fatigue_risk_summary(
        athlete_id=athlete_id,
        reference_date=reference_date,
    )


async def get_my_fatigue_risk_summary(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve el resumen de riesgo de fatiga para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_fatigue_risk_summary(
        access_code=access_code,
        reference_date=reference_date,
    )


async def get_week_strategy_summary(
    athlete_id: int,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Resume la logica de la semana e infiere una etiqueta simple de estrategia sin usar IA."""
    return await CLIENT.get_week_strategy_summary(
        athlete_id=athlete_id,
        week_start_date=week_start_date,
    )


async def get_my_week_strategy_summary(
    access_code: str,
    week_start_date: str | None = None,
) -> dict[str, Any]:
    """Resume la estrategia semanal del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_week_strategy_summary(
        access_code=access_code,
        week_start_date=week_start_date,
    )


async def get_training_dashboard(
    athlete_id: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compone un panorama general read-only con readiness, semana actual, riesgo y proxima sesion."""
    return await CLIENT.get_training_dashboard(
        athlete_id=athlete_id,
        reference_date=reference_date,
    )


async def get_my_training_dashboard(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compone el panorama general del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_training_dashboard(
        access_code=access_code,
        reference_date=reference_date,
    )


async def get_plan_adjustment_suggestions(
    athlete_id: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve sugerencias read-only de ajuste semanal segun riesgo, sesiones pendientes y estrategia actual."""
    return await CLIENT.get_plan_adjustment_suggestions(
        athlete_id=athlete_id,
        reference_date=reference_date,
    )


async def get_my_plan_adjustment_suggestions(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Devuelve sugerencias de ajuste para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_plan_adjustment_suggestions(
        access_code=access_code,
        reference_date=reference_date,
    )


async def get_next_session_decision(
    athlete_id: int,
    reference_date: str | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Devuelve una decision read-only sobre la proxima sesion o una sesion objetivo concreta."""
    return await CLIENT.get_next_session_decision(
        athlete_id=athlete_id,
        reference_date=reference_date,
        planned_session_id=planned_session_id,
    )


async def get_my_next_session_decision(
    access_code: str,
    reference_date: str | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Devuelve la decision sobre la proxima sesion del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_next_session_decision(
        access_code=access_code,
        reference_date=reference_date,
        planned_session_id=planned_session_id,
    )


async def get_optional_session_impact(
    athlete_id: int,
    planned_session_id: int | None = None,
    date: str | None = None,
    sport: str | None = None,
) -> dict[str, Any]:
    """Evalua el impacto de omitir una sesion objetivo sin modificar el plan."""
    return await CLIENT.get_optional_session_impact(
        athlete_id=athlete_id,
        planned_session_id=planned_session_id,
        date=date,
        sport=sport,
    )


async def get_my_optional_session_impact(
    access_code: str,
    planned_session_id: int | None = None,
    date: str | None = None,
    sport: str | None = None,
) -> dict[str, Any]:
    """Evalua el impacto de omitir una sesion del atleta resuelto por su clave privada."""
    return await CLIENT.get_my_optional_session_impact(
        access_code=access_code,
        planned_session_id=planned_session_id,
        date=date,
        sport=sport,
    )


async def generate_plan_adjustment_import_text(
    athlete_id: int,
    adjustment_type: str,
    reference_date: str | None = None,
    planned_session_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Genera un bloque importable V2 como texto para preview posterior, sin aplicar cambios."""
    return await CLIENT.generate_plan_adjustment_import_text(
        athlete_id=athlete_id,
        adjustment_type=adjustment_type,
        reference_date=reference_date,
        planned_session_id=planned_session_id,
        reason=reason,
    )


async def get_my_plan_adjustment_import_text(
    access_code: str,
    adjustment_type: str,
    reference_date: str | None = None,
    planned_session_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Genera texto importable V2 para el atleta resuelto por su clave privada, sin aplicar cambios."""
    return await CLIENT.get_my_plan_adjustment_import_text(
        access_code=access_code,
        adjustment_type=adjustment_type,
        reference_date=reference_date,
        planned_session_id=planned_session_id,
        reason=reason,
    )


async def get_training_decision_context(
    athlete_id: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compone el contexto clave que conviene mirar antes de tocar el plan."""
    return await CLIENT.get_training_decision_context(
        athlete_id=athlete_id,
        reference_date=reference_date,
    )


async def get_my_training_decision_context(
    access_code: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compone el contexto de decision para el atleta resuelto por su clave privada."""
    return await CLIENT.get_my_training_decision_context(
        access_code=access_code,
        reference_date=reference_date,
    )


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


async def get_session_metrics_json(
    athlete_id: int,
    planned_session_id: int | None = None,
    activity_id: int | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Devuelve planned_session, activity y metrics_json completo como fuente principal para analisis conversacional de sesiones."""
    return await CLIENT.get_session_metrics_json(
        athlete_id=athlete_id,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date=date,
    )


async def get_my_session_metrics_json(
    access_code: str,
    date: str | None = None,
    activity_id: int | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Devuelve planned_session, activity y metrics_json completo solo para el atleta resuelto por la clave privada."""
    return await CLIENT.get_my_session_metrics_json(
        access_code=access_code,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date=date,
    )


async def get_session_block_analysis_payload(
    athlete_id: int,
    planned_session_id: int | None = None,
    activity_id: int | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Devuelve un payload tecnico fino por bloques y laps para una sesion o actividad concreta."""
    return await CLIENT.get_session_block_analysis_payload(
        athlete_id=athlete_id,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date=date,
    )


async def get_my_session_block_analysis_payload(
    access_code: str,
    date: str | None = None,
    activity_id: int | None = None,
    planned_session_id: int | None = None,
) -> dict[str, Any]:
    """Devuelve el payload fino de analisis por bloques solo para el atleta resuelto por la clave privada."""
    return await CLIENT.get_my_session_block_analysis_payload(
        access_code=access_code,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date=date,
    )


async def preview_plan_import(import_text: str) -> dict[str, Any]:
    """Previsualiza una importacion semanal o individual de planificacion sin escribir en la base."""
    return await CLIENT.preview_plan_import(import_text=import_text)


async def verify_plan_import(import_text: str) -> dict[str, Any]:
    """Verifica en modo read-only que un bloque importable haya quedado reflejado en la base sin aplicar cambios."""
    return await CLIENT.verify_plan_import(import_text=import_text)


async def commit_plan_import(import_text: str, confirmation: str) -> dict[str, Any]:
    """Aplica una importacion de planificacion. Requiere confirmation='APLICAR' y token de escritura."""
    return await CLIENT.commit_plan_import(import_text=import_text, confirmation=confirmation)


def _register_public_tools() -> None:
    registered: set[str] = set()
    for tool_name in PUBLIC_MCP_TOOL_NAMES:
        tool_func = globals().get(tool_name)
        if tool_func is None:
            raise RuntimeError(f"Tool publica no encontrada: {tool_name}")
        if tool_name in registered:
            raise RuntimeError(f"Tool publica duplicada: {tool_name}")
        mcp.tool()(tool_func)
        registered.add(tool_name)


_register_public_tools()


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
