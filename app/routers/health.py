from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.db.session import get_db
from app.config import get_settings
from app.schemas.daily_health_metric import DailyHealthMetricRead
from app.services.auth_context import require_current_user
from app.services.daily_health_metric_service import get_health_metric, get_health_metrics
from app.services.athlete_context import get_current_athlete
from app.services.health_ai_analysis_service import (
    get_latest_health_ai_analysis_for_date,
    get_or_create_health_ai_analysis,
    list_health_ai_analyses_for_athlete,
)
from app.services.health_auto_sync_service import (
    build_health_sync_view,
    get_health_sync_state,
    run_health_auto_sync,
    serialize_health_sync_state,
    should_auto_sync_health,
    utc_now,
)
from app.services.health_readiness_service import (
    build_health_readiness_summary,
    build_health_training_context,
    evaluate_health_readiness,
)
from app.services.openai_client import OpenAIIntegrationError
from app.services.user_permission_service import require_can_edit_athlete, require_can_sync_garmin, require_can_view_athlete
from app.utils.datetime_utils import format_local_datetime, today_local
from app.web.templates import build_templates


router = APIRouter(prefix="/health", tags=["health"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


def _coerce_selected_date(value: str | None) -> tuple[date, bool]:
    if not value:
        return today_local(), False
    try:
        return date.fromisoformat(value), False
    except ValueError:
        return today_local(), True


def _resolve_health_athlete(db: Session, athlete_id: int | None, metrics: list[Any]) -> Athlete | None:
    if athlete_id is not None:
        return db.get(Athlete, athlete_id)
    # Fallback legacy: only infer from metrics when there is a single athlete represented.
    metric_athlete_ids = {metric.athlete_id for metric in metrics if getattr(metric, "athlete_id", None)}
    if len(metric_athlete_ids) == 1:
        return db.get(Athlete, next(iter(metric_athlete_ids)))
    return db.scalar(select(Athlete).order_by(Athlete.created_at.asc(), Athlete.id.asc()))


def _health_readiness_status_class(status: str) -> str:
    mapping = {
        "green": "health-readiness-status-green",
        "yellow": "health-readiness-status-yellow",
        "orange": "health-readiness-status-orange",
        "red": "health-readiness-status-red",
        "insufficient_data": "health-readiness-status-insufficient",
    }
    return mapping.get(status, "health-readiness-status-insufficient")


def _health_readiness_score_label(score: int | None) -> str:
    return "-" if score is None else f"{score}/100"


def _ui_health_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    replacements = [
        ("Readiness", "Estado"),
        ("readiness", "estado"),
        ("Recovery score", "Estado general"),
        ("recovery score", "estado general"),
        ("HRV status", "variabilidad cardiaca"),
        ("hrv status", "variabilidad cardiaca"),
    ]
    for source, target in replacements:
        text = text.replace(source, target)
    return text


def _ui_status_recommendation(status: str) -> str:
    mapping = {
        "green": "Entrenar normal",
        "yellow": "Controlar carga",
        "orange": "Solo suave / recuperacion",
        "red": "Descanso recomendado",
        "insufficient_data": "Sin datos suficientes",
    }
    return mapping.get(status, "Sin datos suficientes")


def _build_health_metric_overview(summary: Any) -> list[dict[str, str]]:
    return [
        {"label": "Sueno promedio 7d", "value": _hours_label(summary.sleep_avg_7d)},
        {"label": "FC reposo 3d vs 14d", "value": _resting_hr_delta_label(summary.resting_hr_avg_3d, summary.resting_hr_avg_14d, summary.resting_hr_delta_3d_vs_14d)},
        {"label": "HRV tendencia", "value": _hrv_trend_label(summary.hrv_trend)},
        {"label": "Estres 3d", "value": _number_label(summary.stress_avg_3d)},
        {"label": "Body Battery manana 3d", "value": _number_label(summary.body_battery_morning_avg_3d)},
        {"label": "Dias disponibles 14d", "value": f"{summary.available_days_14d}/14"},
    ]


def _serialize_health_ai_analysis(analysis: Any | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "reference_date": analysis.reference_date.isoformat(),
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "created_at_label": format_local_datetime(analysis.created_at),
        "updated_at": analysis.updated_at.isoformat() if getattr(analysis, "updated_at", None) else None,
        "updated_at_label": format_local_datetime(getattr(analysis, "updated_at", None)),
        "summary": _ui_health_text(analysis.summary),
        "training_recommendation": _ui_health_text(analysis.training_recommendation),
        "risk_level": analysis.risk_level,
        "model_name": analysis.model_name,
        "source": getattr(analysis, "source", None),
        "llm_json_hash": analysis.llm_json_hash,
        "main_factors": list((analysis.ai_response_json or {}).get("main_factors") or []),
        "what_to_watch": list((analysis.ai_response_json or {}).get("what_to_watch") or []),
        "not_medical_advice": bool((analysis.ai_response_json or {}).get("not_medical_advice", True)),
    }


def _serialize_health_ai_analysis_history(analyses: list[Any], athlete_id: int | None) -> list[dict[str, Any]]:
    history_rows: list[dict[str, Any]] = []
    for analysis in analyses:
        llm_json = analysis.llm_json or {}
        readiness_local = llm_json.get("readiness_local") or {}
        history_rows.append(
            {
                "id": analysis.id,
                "reference_date": analysis.reference_date.isoformat(),
                "reference_date_label": analysis.reference_date.strftime("%d/%m/%Y"),
                "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
                "created_at_label": format_local_datetime(analysis.created_at),
                "readiness_status": readiness_local.get("readiness_status"),
                "readiness_status_label": _ui_status_recommendation(readiness_local.get("readiness_status") or "insufficient_data"),
                "readiness_status_class": _health_readiness_status_class(readiness_local.get("readiness_status") or "insufficient_data"),
                "readiness_score": readiness_local.get("readiness_score"),
                "risk_level": analysis.risk_level or "unknown",
                "risk_level_label": (analysis.risk_level or "unknown").replace("_", " "),
                "summary": _ui_health_text(analysis.summary) or "-",
                "view_date_url": (
                    "/health?"
                    + "&".join(
                        part
                        for part in [
                            f"selected_date={analysis.reference_date.isoformat()}",
                            f"athlete_id={athlete_id}" if athlete_id is not None else "",
                        ]
                        if part
                    )
                ),
            }
        )
    return history_rows


def _serialize_health_ai_analysis_trend(analyses: list[Any]) -> dict[str, Any]:
    trend_points: list[dict[str, Any]] = []
    for analysis in analyses:
        llm_json = analysis.llm_json or {}
        readiness_local = llm_json.get("readiness_local") or {}
        readiness_score = readiness_local.get("readiness_score")
        if readiness_score is None:
            continue
        try:
            score_value = int(readiness_score)
        except (TypeError, ValueError):
            continue

        trend_points.append(
            {
                "reference_date": analysis.reference_date.isoformat(),
                "reference_date_label": analysis.reference_date.strftime("%d/%m"),
                "readiness_score": max(0, min(100, score_value)),
                "readiness_status": readiness_local.get("readiness_status") or "insufficient_data",
                "readiness_status_label": _ui_status_recommendation(readiness_local.get("readiness_status") or "insufficient_data"),
                "readiness_status_class": _health_readiness_status_class(readiness_local.get("readiness_status") or "insufficient_data"),
                "risk_level": analysis.risk_level or "unknown",
                "risk_level_label": (analysis.risk_level or "unknown").replace("_", " "),
            }
        )

    trend_points = list(reversed(trend_points))
    return {
        "points": trend_points,
        "has_enough_points": len(trend_points) >= 2,
    }


def _build_training_context_view(training_context: dict[str, Any]) -> dict[str, Any]:
    next_goal = training_context.get("next_goal_name")
    days_to_goal = training_context.get("days_to_next_goal")
    items = [
        {"label": "Actividades 7d", "value": str(training_context.get("completed_activities_last_7d") or 0)},
        {"label": "Sesiones planificadas 7d", "value": str(training_context.get("planned_sessions_last_7d") or 0)},
        {"label": "Sesiones duras 7d", "value": str(training_context.get("hard_sessions_last_7d") or 0)},
        {"label": "Ultima actividad", "value": _date_iso_label(training_context.get("last_activity_date"))},
        {"label": "Ultimo entrenamiento duro", "value": _date_iso_label(training_context.get("last_hard_session_date"))},
        {"label": "Minutos totales 7d", "value": _number_label(training_context.get("total_duration_minutes_last_7d"))},
        {"label": "Km totales 7d", "value": _number_label(training_context.get("total_distance_km_last_7d"))},
    ]
    if next_goal:
        items.append({"label": "Proximo objetivo", "value": str(next_goal)})
        items.append({"label": "Dias al objetivo", "value": _number_label(days_to_goal)})

    has_recent_data = any(
        [
            (training_context.get("completed_activities_last_7d") or 0) > 0,
            (training_context.get("planned_sessions_last_7d") or 0) > 0,
            bool(training_context.get("last_activity_date")),
            bool(next_goal),
        ]
    )
    return {
        "has_recent_data": has_recent_data,
        "metric_items": items,
    }


def _decision_title(status: str) -> str:
    mapping = {
        "green": "ENTRENAR NORMAL",
        "yellow": "CONTROLAR CARGA",
        "orange": "SOLO SUAVE / RECUPERACION",
        "red": "DESCANSO RECOMENDADO",
        "insufficient_data": "SIN DATOS SUFICIENTES",
    }
    return mapping.get(status, "SIN DATOS SUFICIENTES")


def _decision_interpretation(evaluation: Any, summary: Any, training_context: dict[str, Any]) -> str:
    status = evaluation.readiness_status
    hard_sessions = int(training_context.get("hard_sessions_last_7d") or 0)
    if status == "green":
        if hard_sessions >= 4:
            return "La recuperacion es razonable, aunque venis acumulando bastante carga reciente."
        return "La recuperacion parece buena para entrenar normal."
    if status == "yellow":
        if summary.hrv_trend == "down":
            return "Hay senales para controlar la carga de hoy y evitar pasarte con la intensidad."
        return "El estado general es aceptable, pero conviene entrenar con control."
    if status == "orange":
        return "Venis con signos de fatiga acumulada y hoy conviene bajar la exigencia."
    if status == "red":
        return "Hoy no parece un buen dia para intensidad alta."
    return "Todavia no hay suficientes datos para interpretar el estado deportivo de forma confiable."


def _decision_factors(evaluation: Any, summary: Any, training_context: dict[str, Any]) -> list[str]:
    factors: list[str] = []
    for reason in list(evaluation.reasons or []):
        cleaned = str(reason).strip()
        if cleaned and cleaned not in factors:
            factors.append(cleaned)

    hard_sessions = int(training_context.get("hard_sessions_last_7d") or 0)
    if hard_sessions >= 4:
        factors.append(f"{hard_sessions} sesiones duras en los ultimos 7 dias.")
    elif hard_sessions >= 2:
        factors.append(f"{hard_sessions} sesiones duras recientes.")

    if summary.hrv_trend == "down":
        factors.append("La HRV viene en descenso.")

    last_activity_date = training_context.get("last_activity_date")
    if last_activity_date == summary.reference_date.isoformat():
        factors.append("Hubo actividad registrada hoy.")

    if summary.sleep_avg_7d is not None and summary.sleep_avg_7d < 6.75:
        factors.append("El sueno reciente fue insuficiente.")

    deduped: list[str] = []
    for item in factors:
        normalized = item.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:3]


def _metric_status_tokens(status: str) -> tuple[str, str]:
    mapping = {
        "green": ("health-readiness-status-green", "Verde"),
        "yellow": ("health-readiness-status-yellow", "Amarillo"),
        "orange": ("health-readiness-status-orange", "Naranja"),
        "red": ("health-readiness-status-red", "Rojo"),
        "insufficient_data": ("health-readiness-status-insufficient", "Sin datos"),
    }
    return mapping.get(status, mapping["insufficient_data"])


def _build_human_signal_items(summary: Any, training_context: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    sleep_value = summary.sleep_avg_7d
    if sleep_value is None:
        sleep_status, sleep_label, sleep_detail = "insufficient_data", "Sin datos", "Faltan datos recientes de sueno."
    elif sleep_value >= 7.5:
        sleep_status, sleep_label, sleep_detail = "green", "Bueno", f"Promedio 7d: {sleep_value:.1f} h"
    elif sleep_value >= 6.75:
        sleep_status, sleep_label, sleep_detail = "yellow", "Aceptable", f"Promedio 7d: {sleep_value:.1f} h"
    elif sleep_value >= 6.0:
        sleep_status, sleep_label, sleep_detail = "orange", "Corto", f"Promedio 7d: {sleep_value:.1f} h"
    else:
        sleep_status, sleep_label, sleep_detail = "red", "Muy corto", f"Promedio 7d: {sleep_value:.1f} h"
    items.append(_build_signal_item("sleep", "Sueno", "Dormir", sleep_status, sleep_label, sleep_detail))

    body_battery = summary.body_battery_morning_avg_3d
    hrv_trend = summary.hrv_trend
    if body_battery is None and not hrv_trend:
        recovery_status, recovery_label, recovery_detail = "insufficient_data", "Sin datos", "No hay una lectura clara de recuperacion."
    elif body_battery is not None and body_battery < 35:
        recovery_status, recovery_label, recovery_detail = "red", "Recuperacion baja", f"Body Battery 3d: {body_battery:.0f}"
    elif hrv_trend == "down" or (body_battery is not None and body_battery < 50):
        recovery_status, recovery_label, recovery_detail = "orange", "Baja", _recovery_detail_text(hrv_trend, body_battery)
    elif hrv_trend == "stable" or (body_battery is not None and body_battery < 65):
        recovery_status, recovery_label, recovery_detail = "yellow", "Aceptable", _recovery_detail_text(hrv_trend, body_battery)
    else:
        recovery_status, recovery_label, recovery_detail = "green", "Buena", _recovery_detail_text(hrv_trend, body_battery)
    items.append(_build_signal_item("recovery", "Recuperacion", "Rec", recovery_status, recovery_label, recovery_detail))

    hard_sessions = int(training_context.get("hard_sessions_last_7d") or 0)
    if hard_sessions >= 5:
        load_status, load_label, load_detail = "red", "Muy exigente", f"{hard_sessions} sesiones duras en 7 dias"
    elif hard_sessions >= 4:
        load_status, load_label, load_detail = "orange", "Exigente", f"{hard_sessions} sesiones duras en 7 dias"
    elif hard_sessions >= 2:
        load_status, load_label, load_detail = "yellow", "Moderada", f"{hard_sessions} sesiones duras en 7 dias"
    else:
        load_status, load_label, load_detail = "green", "Ligera", f"{hard_sessions} sesiones duras en 7 dias"
    items.append(_build_signal_item("load", "Carga reciente", "Carga", load_status, load_label, load_detail))

    stress_value = summary.stress_avg_3d
    if stress_value is None:
        stress_status, stress_label, stress_detail = "insufficient_data", "Sin datos", "No hay promedio reciente de estres."
    elif stress_value >= 60:
        stress_status, stress_label, stress_detail = "red", "Alto", f"Promedio 3d: {stress_value:.0f}"
    elif stress_value >= 45:
        stress_status, stress_label, stress_detail = "orange", "Elevado", f"Promedio 3d: {stress_value:.0f}"
    elif stress_value >= 30:
        stress_status, stress_label, stress_detail = "yellow", "Moderado", f"Promedio 3d: {stress_value:.0f}"
    else:
        stress_status, stress_label, stress_detail = "green", "Bajo", f"Promedio 3d: {stress_value:.0f}"
    items.append(_build_signal_item("stress", "Estres", "Estres", stress_status, stress_label, stress_detail))
    return items


def _build_signal_item(key: str, label: str, badge: str, status: str, state_label: str, detail: str) -> dict[str, str]:
    status_class, tone_label = _metric_status_tokens(status)
    return {
        "key": key,
        "label": label,
        "badge": badge,
        "status": status,
        "status_class": status_class,
        "tone_label": tone_label,
        "state_label": state_label,
        "detail": detail,
    }


def _recovery_detail_text(hrv_trend: str | None, body_battery: float | None) -> str:
    parts: list[str] = []
    if hrv_trend == "up":
        parts.append("HRV en mejora")
    elif hrv_trend == "down":
        parts.append("HRV en descenso")
    elif hrv_trend == "stable":
        parts.append("HRV estable")
    if body_battery is not None:
        parts.append(f"Body Battery 3d: {body_battery:.0f}")
    return " · ".join(parts) if parts else "Recuperacion sin datos claros."


def _build_compact_context(training_context: dict[str, Any], reference_date: date) -> dict[str, Any]:
    items: list[str] = []
    completed = int(training_context.get("completed_activities_last_7d") or 0)
    planned = int(training_context.get("planned_sessions_last_7d") or 0)
    hard = int(training_context.get("hard_sessions_last_7d") or 0)
    minutes = training_context.get("total_duration_minutes_last_7d")
    km = training_context.get("total_distance_km_last_7d")
    last_activity_date = training_context.get("last_activity_date")
    next_goal = training_context.get("next_goal_name")
    days_to_goal = training_context.get("days_to_next_goal")

    items.append(f"{completed} actividades realizadas")
    items.append(f"{planned} sesiones planificadas")
    items.append(f"{hard} sesiones duras")
    if minutes is not None:
        items.append(f"{_number_label(minutes)} min totales")
    if km is not None:
        items.append(f"{_number_label(km)} km")
    if last_activity_date:
        items.append(f"Ultima actividad: {_relative_date_label(last_activity_date, reference_date)}")
    if next_goal:
        goal_text = f"Proximo objetivo: {next_goal}"
        if days_to_goal is not None:
            goal_text += f" ({days_to_goal} dias)"
        items.append(goal_text)

    has_recent_data = any(
        [
            completed > 0,
            planned > 0,
            hard > 0,
            minutes is not None,
            km is not None,
            bool(next_goal),
        ]
    )
    return {"has_recent_data": has_recent_data, "items": items}


def _relative_date_label(value: str, reference_date: date) -> str:
    try:
        target_date = date.fromisoformat(value)
    except ValueError:
        return value
    delta = (reference_date - target_date).days
    if delta <= 0:
        return "hoy"
    if delta == 1:
        return "ayer"
    return f"hace {delta} dias"


def _build_recent_trend_view(recent_ai_trend: dict[str, Any]) -> dict[str, Any]:
    points = list(recent_ai_trend.get("points") or [])
    if len(points) < 2:
        return {
            "has_enough_points": False,
            "points": points,
            "direction_label": None,
            "interpretation": None,
        }

    first_score = int(points[0]["readiness_score"])
    last_score = int(points[-1]["readiness_score"])
    delta = last_score - first_score
    if delta >= 8:
        direction_label = "Subida reciente"
        interpretation = "Mejora reciente en la recuperacion."
    elif delta <= -8:
        direction_label = "Caida reciente"
        interpretation = "La recuperacion viene bajando hace varios dias."
    else:
        direction_label = "Estable"
        interpretation = "Estado estable durante la ultima semana."

    normalized_points: list[dict[str, Any]] = []
    for point in points:
        normalized_points.append(
            {
                **point,
                "score_label": f"{point['readiness_score']}",
                "status_short_label": point.get("readiness_status_label") or "-",
            }
        )

    return {
        "has_enough_points": True,
        "points": normalized_points,
        "direction_label": direction_label,
        "interpretation": interpretation,
    }


def _build_health_readiness_view_model(
    db: Session,
    *,
    athlete_id: int | None,
    selected_date: date,
    metrics: list[Any] | None = None,
) -> dict[str, Any]:
    metric_rows = metrics if metrics is not None else get_health_metrics(db)
    athlete = _resolve_health_athlete(db, athlete_id, metric_rows)

    if athlete is None:
        return {
            "athlete_id": None,
            "athlete_name": None,
            "selected_date": selected_date.isoformat(),
            "selected_date_label": selected_date.strftime("%d/%m/%Y"),
            "summary": None,
            "evaluation": {
                "readiness_score": None,
                "readiness_status": "insufficient_data",
                "readiness_label": "datos insuficientes",
                "recommendation_display": _ui_status_recommendation("insufficient_data"),
                "main_limiter": None,
                "reasons": [],
                "recommendation": "Todavia no hay datos suficientes para evaluar la tendencia. Hacen falta al menos 5 dias dentro de los ultimos 14.",
                "data_quality": "poor",
                "data_quality_reasons": ["Todavia no hay un atleta o metricas diarias disponibles para construir la tendencia."],
            },
            "status_class": _health_readiness_status_class("insufficient_data"),
            "score_label": "-",
            "main_limiter_label": None,
            "reason_items": [],
            "metric_overview": [],
            "sync_state": None,
            "sync_view": build_health_sync_view(None, should_auto_sync=False),
            "should_auto_sync": False,
            "should_auto_ai_analysis": False,
            "can_generate_ai_analysis": False,
            "can_regenerate_ai_analysis": False,
            "ai_analysis_button_label": "Generar analisis ahora",
            "ai_analysis_empty_message": "Todavia no hay analisis IA de salud para esta fecha.",
            "health_auto_sync_url": "",
            "decision_card": {
                "title": _decision_title("insufficient_data"),
                "status_class": _health_readiness_status_class("insufficient_data"),
                "interpretation": "Todavia no hay suficientes datos para interpretar el estado deportivo de forma confiable.",
                "factors": [],
                "score_label": "-",
                "reference_label": selected_date.strftime("%d/%m/%Y"),
            },
            "human_signals": _build_human_signal_items(
                type("Summary", (), {
                    "sleep_avg_7d": None,
                    "body_battery_morning_avg_3d": None,
                    "hrv_trend": None,
                    "stress_avg_3d": None,
                })(),
                {},
            ),
            "compact_training_context": {"has_recent_data": False, "items": []},
            "recent_trend_view": {"has_enough_points": False, "points": [], "direction_label": None, "interpretation": None},
        }

    summary = build_health_readiness_summary(db, athlete.id, selected_date)
    evaluation = evaluate_health_readiness(summary)
    training_context = build_health_training_context(db, athlete.id, selected_date)
    latest_ai_analysis = get_latest_health_ai_analysis_for_date(db, athlete.id, selected_date)
    recent_ai_analyses = list_health_ai_analyses_for_athlete(db, athlete.id, limit=10)
    recent_ai_trend = _serialize_health_ai_analysis_trend(recent_ai_analyses)
    sync_state = get_health_sync_state(db, athlete.id)
    should_sync = should_auto_sync_health(sync_state, utc_now(), selected_date)
    today = today_local(athlete=athlete)

    def build_health_url(target_date: date) -> str:
        query = [f"selected_date={target_date.isoformat()}"]
        if athlete.id is not None:
            query.append(f"athlete_id={athlete.id}")
        return "/health?" + "&".join(query)

    return {
        "athlete_id": athlete.id,
        "athlete_name": athlete.name,
        "selected_date": selected_date.isoformat(),
        "selected_date_label": selected_date.strftime("%d/%m/%Y"),
        "quick_nav": {
            "yesterday_url": build_health_url(selected_date - timedelta(days=1)),
            "minus_7d_url": build_health_url(selected_date - timedelta(days=7)),
            "plus_1d_url": None if selected_date >= today else build_health_url(selected_date + timedelta(days=1)),
            "today_url": build_health_url(today),
            "is_today": selected_date == today,
        },
        "summary": summary.model_dump(),
        "evaluation": {
            **evaluation.model_dump(),
            "readiness_label": _ui_status_recommendation(evaluation.readiness_status),
            "recommendation_display": _ui_status_recommendation(evaluation.readiness_status),
            "recommendation": _ui_health_text(evaluation.recommendation),
        },
        "status_class": _health_readiness_status_class(evaluation.readiness_status),
        "score_label": _health_readiness_score_label(evaluation.readiness_score),
        "main_limiter_label": _main_limiter_label(evaluation.main_limiter),
        "reason_items": evaluation.reasons[:3],
        "metric_overview": _build_health_metric_overview(summary),
        "training_context": training_context,
        "training_context_view": _build_training_context_view(training_context),
        "sync_state": serialize_health_sync_state(sync_state),
        "sync_view": build_health_sync_view(sync_state, should_auto_sync=should_sync),
        "should_auto_sync": should_sync,
        "should_auto_ai_analysis": False,
        "can_generate_ai_analysis": latest_ai_analysis is None,
        "can_regenerate_ai_analysis": latest_ai_analysis is not None,
        "ai_analysis_button_label": "Regenerar analisis" if latest_ai_analysis is not None else "Generar analisis ahora",
        "ai_analysis_empty_message": "Todavia no hay analisis IA de salud para esta fecha.",
        "health_auto_sync_url": f"/health/auto-sync?selected_date={selected_date.isoformat()}&athlete_id={athlete.id}",
        "latest_ai_analysis": _serialize_health_ai_analysis(latest_ai_analysis),
        "recent_ai_history": _serialize_health_ai_analysis_history(recent_ai_analyses[:5], athlete.id),
        "recent_ai_trend": recent_ai_trend,
        "decision_card": {
            "title": _decision_title(evaluation.readiness_status),
            "status_class": _health_readiness_status_class(evaluation.readiness_status),
            "interpretation": _decision_interpretation(evaluation, summary, training_context),
            "factors": _decision_factors(evaluation, summary, training_context),
            "score_label": _health_readiness_score_label(evaluation.readiness_score),
            "reference_label": selected_date.strftime("%d/%m/%Y"),
        },
        "human_signals": _build_human_signal_items(summary, training_context),
        "compact_training_context": _build_compact_context(training_context, selected_date),
        "recent_trend_view": _build_recent_trend_view(recent_ai_trend),
    }


def _hours_label(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f} h"


def _number_label(value: float | None) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _date_iso_label(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _resting_hr_delta_label(avg_3d: float | None, avg_14d: float | None, delta: float | None) -> str:
    if avg_3d is None or avg_14d is None or delta is None:
        return "-"
    sign = "+" if delta > 0 else ""
    return f"{_number_label(avg_3d)} vs {_number_label(avg_14d)} ({sign}{delta:.1f})"


def _hrv_trend_label(value: str | None) -> str:
    mapping = {
        "up": "subiendo",
        "down": "bajando",
        "stable": "estable",
        "insufficient_data": "sin datos suficientes",
    }
    return mapping.get(value or "", "-")


def _main_limiter_label(value: str | None) -> str | None:
    mapping = {
        "hrv": "HRV",
        "resting_hr": "FC reposo",
        "sleep": "Sueno",
        "body_battery": "Body Battery",
        "stress": "Estres",
    }
    return mapping.get(value or "")


@router.get("", response_model=list[DailyHealthMetricRead])
def list_health_metrics(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = None,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    metrics = get_health_metrics(db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is None and _wants_html(request):
        return RedirectResponse(url="/athletes/select", status_code=303)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        require_can_view_athlete(db, user, athlete_id)
        metrics = [metric for metric in metrics if metric.athlete_id == current_athlete.id]
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    if not selected_date and current_athlete is not None:
        selected_date_value = today_local(athlete=current_athlete)
    readiness_view = _build_health_readiness_view_model(
        db,
        athlete_id=athlete_id,
        selected_date=selected_date_value,
        metrics=metrics,
    )
    if _wants_html(request):
        ui_status = request.query_params.get("ui_status")
        if invalid_selected_date:
            ui_status = "La fecha seleccionada no era valida. Se mostro el estado de hoy."
        return templates.TemplateResponse(
            request=request,
            name="health/list.html",
            context={
                "metrics": metrics,
                "readiness": readiness_view,
                "ui_status": ui_status,
            },
        )
    return metrics


@router.get("/readiness")
def read_health_readiness(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        require_can_view_athlete(db, user, athlete_id)
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    if not selected_date and current_athlete is not None:
        selected_date_value = today_local(athlete=current_athlete)
    if invalid_selected_date:
        return {
            "error": "invalid_selected_date",
            "message": "selected_date debe tener formato YYYY-MM-DD.",
            "fallback_date": selected_date_value.isoformat(),
            "readiness": _build_health_readiness_view_model(
                db,
                athlete_id=athlete_id,
                selected_date=selected_date_value,
            ),
        }
    return _build_health_readiness_view_model(
        db,
        athlete_id=athlete_id,
        selected_date=selected_date_value,
    )


@router.post("/auto-sync")
def auto_sync_health(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        require_can_sync_garmin(db, user, athlete_id)
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    if not selected_date and current_athlete is not None:
        selected_date_value = today_local(athlete=current_athlete)
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return JSONResponse(
            status_code=404,
            content={
                "synced": False,
                "reason": "athlete_not_found",
                "message": "No se encontro un atleta para sincronizar salud.",
            },
        )

    result = run_health_auto_sync(
        db,
        athlete_id=athlete.id,
        settings=get_settings(),
        reference_date=selected_date_value,
        force=force,
    )
    if invalid_selected_date:
        result["warning"] = "selected_date invalida; se uso la fecha de hoy."
    return result


@router.get("/readiness/llm-json")
def read_health_readiness_llm_json(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        require_can_view_athlete(db, user, athlete_id)
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    if not selected_date and current_athlete is not None:
        selected_date_value = today_local(athlete=current_athlete)
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return {
            "error": "athlete_not_found",
            "message": "No se encontro un atleta para construir el JSON de salud.",
        }

    summary = build_health_readiness_summary(db, athlete.id, selected_date_value)
    evaluation = evaluate_health_readiness(summary)
    training_context = build_health_training_context(db, athlete.id, selected_date_value)
    from app.services.health_readiness_service import build_health_llm_json

    payload = build_health_llm_json(athlete, summary, evaluation, selected_date_value, training_context=training_context)
    if invalid_selected_date:
        return {
            "error": "invalid_selected_date",
            "message": "selected_date debe tener formato YYYY-MM-DD.",
            "fallback_date": selected_date_value.isoformat(),
            "payload": payload,
        }
    return payload


@router.post("/readiness/ai-analysis")
def analyze_health_readiness(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        require_can_edit_athlete(db, user, athlete_id)
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    if not selected_date and current_athlete is not None:
        selected_date_value = today_local(athlete=current_athlete)
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "athlete_not_found",
                "message": "No se encontro un atleta para analizar el estado.",
            },
        )

    try:
        saved_analysis, result_kind = get_or_create_health_ai_analysis(
            db,
            athlete_id=athlete.id,
            reference_date=selected_date_value,
            force=force,
            source="manual",
        )
    except OpenAIIntegrationError as exc:
        error_code = "missing_api_key" if "api_key" in str(exc).lower() else "ai_analysis_failed"
        status_code = 503 if error_code == "missing_api_key" else 502
        return JSONResponse(
            status_code=status_code,
            content={
                "error": error_code,
                "message": str(exc),
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": "ai_analysis_failed",
                "message": f"No se pudo analizar el estado con IA: {exc}",
            },
        )

    if saved_analysis is None:
        response_payload: dict[str, Any] = {
            "selected_date": selected_date_value.isoformat(),
            "generated": False,
            "reason": "insufficient_data",
            "message": "Todavia no hay datos suficientes para generar el analisis IA de salud.",
            "saved_analysis": None,
        }
        if invalid_selected_date:
            response_payload["warning"] = "selected_date invalida; se uso la fecha de hoy."
        return response_payload

    response_payload: dict[str, Any] = {
        "selected_date": selected_date_value.isoformat(),
        "generated": result_kind in {"created", "updated"},
        "reason": result_kind,
        "message": (
            "Se actualizo el analisis IA de salud."
            if result_kind == "updated"
            else ("Se genero el analisis IA de salud." if result_kind == "created" else "Ya existia un analisis IA para esta fecha.")
        ),
        "llm_json": saved_analysis.llm_json or {},
        "analysis": saved_analysis.ai_response_json or {},
        "saved_analysis": _serialize_health_ai_analysis(saved_analysis),
    }
    if invalid_selected_date:
        response_payload["warning"] = "selected_date invalida; se uso la fecha de hoy."
    return response_payload


@router.post("/readiness/auto-ai-analysis")
def auto_analyze_health_readiness(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        require_can_edit_athlete(db, user, athlete_id)
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    if not selected_date and current_athlete is not None:
        selected_date_value = today_local(athlete=current_athlete)
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return JSONResponse(
            status_code=404,
            content={
                "ran": False,
                "reason": "athlete_not_found",
                "message": "No se encontro un atleta para analizar el estado.",
            },
        )

    try:
        saved_analysis, result_kind = get_or_create_health_ai_analysis(
            db,
            athlete_id=athlete.id,
            reference_date=selected_date_value,
            force=force,
            source="page_view",
        )
    except OpenAIIntegrationError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ran": False,
                "reason": "ai_analysis_failed",
                "message": str(exc),
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ran": False,
                "reason": "ai_analysis_failed",
                "message": f"No se pudo analizar el estado con IA: {exc}",
            },
        )

    if saved_analysis is None:
        response_payload: dict[str, Any] = {
            "ran": False,
            "reason": "insufficient_data",
            "message": "Todavia no hay datos suficientes para generar el analisis IA de salud.",
            "saved_analysis": None,
        }
        if invalid_selected_date:
            response_payload["warning"] = "selected_date invalida; se uso la fecha de hoy."
        return response_payload

    response_payload: dict[str, Any] = {
        "ran": result_kind in {"created", "updated"},
        "reason": "generated" if result_kind in {"created", "updated"} else "already_analyzed",
        "analysis": saved_analysis.ai_response_json or {},
        "saved_analysis": _serialize_health_ai_analysis(saved_analysis),
        "latest_analysis": _serialize_health_ai_analysis(saved_analysis),
    }
    if invalid_selected_date:
        response_payload["warning"] = "selected_date invalida; se uso la fecha de hoy."
    return response_payload


@router.get("/{metric_id}", response_model=DailyHealthMetricRead)
def read_health_metric(metric_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    metric = get_health_metric(db, metric_id)
    if metric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health metric not found")
    require_can_view_athlete(db, user, metric.athlete_id)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="health/detail.html",
            context={"metric": metric},
        )
    return metric
