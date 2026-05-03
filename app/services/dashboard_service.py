from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.health_sync_state import HealthSyncState
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.services.health_readiness_service import build_health_readiness_summary, evaluate_health_readiness
from app.services.planning.presentation import derive_session_metrics, describe_session_structure_short


APP_LOCAL_TIMEZONE = timezone(timedelta(hours=-3), name="America/Buenos_Aires")


def format_duration_minutes(minutes: int | None) -> str:
    if minutes is None or minutes <= 0:
        return ""
    hours, remaining_minutes = divmod(int(minutes), 60)
    if hours and remaining_minutes:
        return f"{hours} h {remaining_minutes} min"
    if hours:
        return f"{hours} h"
    return f"{remaining_minutes} min"


def build_dashboard_context(
    db: Session,
    athlete,
    training_plan: TrainingPlan | None,
    selected_date: date | None = None,
) -> dict[str, Any]:
    reference_date = selected_date or date.today()
    today_sessions = _get_sessions_for_date(db, athlete.id, training_plan, reference_date)
    today_session = today_sessions[0] if today_sessions else None
    next_session = _get_next_session(db, athlete.id, training_plan, reference_date)
    today_activity = _get_today_activity(db, athlete.id, reference_date, today_session)
    health_metric = _get_health_metric_for_date(db, athlete.id, reference_date)
    health_ai = _get_health_ai_for_date(db, athlete.id, reference_date)
    health_sync_state = _get_health_sync_state(db, athlete.id)
    weekly_summary = _build_weekly_summary(db, athlete.id, reference_date)
    today_status = _build_today_status(reference_date, today_session, today_activity, health_metric, health_ai, athlete.id, db)
    today_session_card = _build_today_session_card(today_session, reference_date, training_plan, len(today_sessions), today_activity)
    today_activity_card = _build_today_activity_card(today_activity)
    next_session_card = _build_next_session_card(next_session)
    health = _build_health_card(reference_date, health_metric, health_ai, health_sync_state, athlete.id, db)
    alerts = build_dashboard_alerts(
        db,
        athlete_id=athlete.id,
        training_plan=training_plan,
        selected_date=reference_date,
        today_session=today_session,
        today_activity=today_activity["activity"],
        health_metric=health_metric,
        today_status=today_status,
    )
    coach_summary = build_today_coach_summary(
        {
            "selected_date": reference_date,
            "today_status": today_status,
            "today_session": today_session_card,
            "today_activity": today_activity_card,
            "health": health,
            "weekly_summary": weekly_summary,
            "next_session": next_session_card,
            "alerts": alerts,
        }
    )
    today_status = {
        **today_status,
        **coach_summary,
    }

    return {
        "athlete": athlete,
        "training_plan": training_plan,
        "selected_date": reference_date,
        "selected_date_iso": reference_date.isoformat(),
        "prev_date_iso": (reference_date - timedelta(days=1)).isoformat(),
        "next_date_iso": (reference_date + timedelta(days=1)).isoformat(),
        "today_date_iso": date.today().isoformat(),
        "today_status": today_status,
        "today_session": today_session_card,
        "today_activity": today_activity_card,
        "next_session": next_session_card,
        "health": health,
        "weekly_summary": weekly_summary,
        "alerts": alerts,
        "critical_alerts": [alert for alert in alerts if alert.get("level") == "danger"],
    }


def build_today_coach_summary(context: dict[str, Any]) -> dict[str, Any]:
    today_status = context["today_status"]
    today_session = context["today_session"]
    today_activity = context["today_activity"]
    next_session = context["next_session"]
    weekly_summary = context["weekly_summary"]
    alerts = context["alerts"]
    status = today_status["status"]
    score = today_status.get("score")

    if today_activity["exists"] and today_activity["has_analysis"]:
        headline = "Actividad realizada y analizada"
        summary = _activity_coach_summary(today_activity)
        recommendation = _post_activity_recommendation(
            next_session=next_session,
            weekly_summary=weekly_summary,
            alerts=alerts,
            status=status,
        )
        decision = _post_activity_decision(next_session=next_session, status=status)
        return {
            "headline": headline,
            "summary": summary,
            "recommendation": recommendation,
            "decision": decision,
            "status_label": today_status["label"],
            "status": status,
        }

    if today_activity["exists"] and not today_activity["has_analysis"]:
        headline = "Actividad realizada, análisis pendiente"
        summary = _activity_coach_summary(today_activity)
        recommendation = "Analizá la actividad para ajustar mejor la próxima sesión."
        decision = "Analizar la actividad antes de ajustar la próxima sesión."
        return {
            "headline": headline,
            "summary": summary,
            "recommendation": recommendation,
            "decision": decision,
            "status_label": today_status["label"],
            "status": status,
        }

    if today_session["exists"]:
        headline = "Sesión pendiente para hoy"
        sport_label = _sport_text(today_session.get("sport"))
        objective = today_session.get("objective") or "Sin objetivo cargado."
        duration = today_session.get("duration_label")
        summary_parts = [today_session["title"]]
        if sport_label:
            summary_parts.append(sport_label)
        if duration:
            summary_parts.append(duration)
        summary = " · ".join(summary_parts) + f". {objective}"
        recommendation = _planned_session_recommendation(
            score=score,
            status=status,
            today_session=today_session,
            next_session=next_session,
        )
        decision = _planned_session_decision(score, next_session)
        return {
            "headline": headline,
            "summary": summary,
            "recommendation": recommendation,
            "decision": decision,
            "status_label": today_status["label"],
            "status": status,
        }

    headline = "Día sin sesión planificada"
    summary = _day_without_session_summary(weekly_summary, alerts)
    recommendation = "Priorizá recuperación o movilidad suave."
    if next_session["exists"] and status in {"loaded", "rest"} and _next_session_is_demanding(next_session):
        recommendation = "Recuperá bien hoy y evitá sumar intensidad extra antes de la próxima sesión."
    decision = _decision_from_recommendation(recommendation)
    return {
        "headline": headline,
        "summary": summary,
        "recommendation": recommendation,
        "decision": decision,
        "status_label": today_status["label"],
        "status": status,
    }


def build_dashboard_alerts(
    db: Session,
    *,
    athlete_id: int,
    training_plan: TrainingPlan | None,
    selected_date: date,
    today_session: PlannedSession | None,
    today_activity: GarminActivity | None,
    health_metric: DailyHealthMetric | None,
    today_status: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if training_plan is None:
        alerts.append(
            {
                "level": "warning",
                "title": "No hay plan activo",
                "message": "Selecciona o crea un plan para ordenar las sesiones.",
                "url": "/training_plans",
                "action_label": "Ver planes",
            }
        )
    elif training_plan.end_date and training_plan.end_date < selected_date:
        alerts.append(
            {
                "level": "warning",
                "title": "Plan vencido",
                "message": "Este plan ya termino. Conviene marcarlo como completado o seleccionar otro.",
                "url": "/training_plans",
                "action_label": "Ver planes",
            }
        )

    if health_metric is None:
        alerts.append(
            {
                "level": "info",
                "title": "Salud sin datos de hoy",
                "message": "Sincroniza Garmin Health para obtener readiness actualizado.",
                "url": f"/health?selected_date={selected_date.isoformat()}&athlete_id={athlete_id}",
                "action_label": "Ir a salud",
            }
        )

    if today_session is not None and today_activity is not None and today_activity.activity_match is None:
        alerts.append(
            {
                "level": "warning",
                "title": "Actividad pendiente de vincular",
                "message": "Hay una actividad de hoy que podria corresponder a la sesion planificada.",
                "url": "/activities",
                "action_label": "Vincular actividad",
            }
        )

    if today_activity is not None and not _activity_has_completed_analysis(db, today_activity, today_session):
        alerts.append(
            {
                "level": "warning",
                "title": "Analisis pendiente",
                "message": "La actividad ya esta registrada pero todavia no tiene analisis.",
                "url": _activity_analysis_url(today_activity, today_session),
                "action_label": "Analizar",
            }
        )

    if today_status["status"] in {"loaded", "rest"} and today_session is not None and _is_demanding_session(today_session):
        alerts.append(
            {
                "level": "danger",
                "title": "Cuidado con la intensidad",
                "message": "El estado de recuperacion es bajo para una sesion exigente.",
                "url": f"/planned_sessions/{today_session.id}",
                "action_label": "Ver sesion",
            }
        )

    if _count_unlinked_recent_activities(db, athlete_id, selected_date) > 0:
        alerts.append(
            {
                "level": "info",
                "title": "Actividades sin vincular",
                "message": "Hay actividades recientes que todavia no estan asociadas a sesiones.",
                "url": "/activities",
                "action_label": "Revisar actividades",
            }
        )

    return alerts


def _build_today_status(
    reference_date: date,
    today_session: PlannedSession | None,
    today_activity_payload: dict[str, Any],
    health_metric: DailyHealthMetric | None,
    health_ai: HealthAiAnalysis | None,
    athlete_id: int,
    db: Session,
) -> dict[str, Any]:
    if health_metric is None:
        return {
            "status": "insufficient_data",
            "label": "Sin datos suficientes",
            "score": None,
            "headline": "Sin datos suficientes",
            "status_label": "Sin datos suficientes",
            "summary": "No hay datos de salud cargados para hoy.",
            "recommendation": "Sincronizá salud para mejorar la recomendación.",
        }

    summary = build_health_readiness_summary(db, athlete_id, reference_date)
    evaluation = evaluate_health_readiness(summary)
    status = _map_readiness_status(evaluation.readiness_score)
    label = _status_label(status)
    summary_text = health_ai.summary if health_ai and health_ai.summary else _default_status_summary(evaluation)
    recommendation = _build_recommendation(
        status=status,
        today_session=today_session,
        today_activity=today_activity_payload["activity"],
        health_ai=health_ai,
    )

    if today_activity_payload["activity"] is not None:
        summary_text = "Ya hay actividad registrada hoy."

    return {
        "status": status,
        "label": label,
        "score": evaluation.readiness_score,
        "headline": label,
        "status_label": label,
        "summary": summary_text,
        "recommendation": recommendation,
    }


def _build_today_session_card(
    session: PlannedSession | None,
    reference_date: date,
    training_plan: TrainingPlan | None,
    session_count: int,
    activity_payload: dict[str, Any],
) -> dict[str, Any]:
    if session is None:
        return {
            "exists": False,
            "session": None,
            "title": "No hay sesion planificada",
            "sport": None,
            "objective": "Día sin trabajo cargado para hoy.",
            "duration_label": None,
            "url": _calendar_url(training_plan, reference_date),
            "count": 0,
            "has_more": False,
            "status_badges": [],
            "status_line": None,
        }

    metrics = derive_session_metrics(session)
    objective = session.description_text or session.target_notes or describe_session_structure_short(session) or "Sin objetivo cargado."
    status_badges: list[str] = []
    status_line = None
    linked_activity = activity_payload.get("activity") if activity_payload.get("is_linked") else None
    if linked_activity is not None:
        status_badges.append("Realizada")
        status_line = f"{session.name} - realizado"
        if activity_payload.get("has_analysis"):
            status_badges.append("Analizada")
    elif activity_payload.get("activity") is not None:
        status_badges.append("Actividad sin vincular")
        status_line = f"{session.name} - pendiente"
    else:
        status_badges.append("Pendiente")
        status_line = f"{session.name} - pendiente"
    return {
        "exists": True,
        "session": session,
        "title": session.name,
        "sport": session.sport_type,
        "objective": objective,
        "duration_label": format_duration_minutes(session.expected_duration_min),
        "url": f"/planned_sessions/{session.id}",
        "count": session_count,
        "has_more": session_count > 1,
        "distance_label": f"{session.expected_distance_km:.1f} km" if session.expected_distance_km is not None else None,
        "derived_title": metrics.title,
        "status_badges": status_badges,
        "status_line": status_line,
    }


def _build_today_activity_card(payload: dict[str, Any]) -> dict[str, Any]:
    activity = payload["activity"]
    if activity is None:
        return {
            "exists": False,
            "activity": None,
            "is_linked": False,
            "has_analysis": False,
            "title": "Todavia no hay actividad registrada",
            "summary": "Todavía no se detectó una actividad para esta fecha.",
            "url": "/activities",
            "analysis_url": None,
            "detail_items": [],
            "link_status_label": "Pendiente",
            "analysis_status_label": "Pendiente",
            "execution_score_pct": None,
        }

    return {
        "exists": True,
        "activity": activity,
        "is_linked": payload["is_linked"],
        "has_analysis": payload["has_analysis"],
        "title": activity.activity_name or "Actividad Garmin",
        "summary": payload["summary"],
        "url": f"/activities/{activity.id}",
        "analysis_url": payload["analysis_url"],
        "detail_items": payload["detail_items"],
        "link_status_label": payload["link_status_label"],
        "analysis_status_label": payload["analysis_status_label"],
        "execution_score_pct": payload["execution_score_pct"],
    }


def _build_next_session_card(session: PlannedSession | None) -> dict[str, Any]:
    if session is None:
        return {
            "exists": False,
            "session": None,
            "date": None,
            "title": "No hay próxima sesión",
            "sport": None,
            "objective": "No hay otra sesión cargada después de la fecha seleccionada.",
            "url": "/training_plans",
            "duration_label": None,
        }

    return {
        "exists": True,
        "session": session,
        "date": session.training_day.day_date if session.training_day else None,
        "title": session.name,
        "sport": session.sport_type,
        "objective": session.description_text or session.target_notes or describe_session_structure_short(session) or "Sin objetivo cargado.",
        "url": f"/planned_sessions/{session.id}",
        "duration_label": format_duration_minutes(session.expected_duration_min),
    }


def _build_health_card(
    reference_date: date,
    metric: DailyHealthMetric | None,
    health_ai: HealthAiAnalysis | None,
    sync_state: HealthSyncState | None,
    athlete_id: int,
    db: Session,
) -> dict[str, Any]:
    if metric is None:
        return {
            "exists": False,
            "readiness_score": None,
            "readiness_label": "Sin datos suficientes",
            "main_limiter": None,
            "last_sync_at": sync_state.last_success_at if sync_state else None,
            "url": f"/health?selected_date={reference_date.isoformat()}&athlete_id={athlete_id}",
            "sleep_hours": None,
            "hrv_value": None,
            "body_battery": None,
            "summary": "No hay métricas de salud para esta fecha.",
            "dashboard_summary": "Sin datos de salud para hoy. Sincronizá Garmin antes de decidir la carga.",
        }

    summary = build_health_readiness_summary(db, athlete_id, reference_date)
    evaluation = evaluate_health_readiness(summary)
    limiter_label = _main_limiter_label(evaluation.main_limiter)
    dashboard_summary = _build_dashboard_health_summary(metric, health_ai, evaluation.readiness_label, limiter_label)
    return {
        "exists": True,
        "readiness_score": evaluation.readiness_score,
        "readiness_label": evaluation.readiness_label,
        "main_limiter": limiter_label,
        "last_sync_at": sync_state.last_success_at if sync_state else None,
        "url": f"/health?selected_date={reference_date.isoformat()}&athlete_id={athlete_id}",
        "sleep_hours": metric.sleep_hours,
        "hrv_value": metric.hrv_value or metric.hrv_avg_ms,
        "body_battery": metric.body_battery_morning or metric.body_battery_start,
        "summary": health_ai.summary if health_ai and health_ai.summary else evaluation.recommendation,
        "recommendation": health_ai.training_recommendation if health_ai and health_ai.training_recommendation else evaluation.recommendation,
        "dashboard_summary": dashboard_summary,
    }


def _build_weekly_summary(db: Session, athlete_id: int, reference_date: date) -> dict[str, Any]:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    analysis = db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start,
        )
        .order_by(WeeklyAnalysis.analyzed_at.desc(), WeeklyAnalysis.id.desc())
    )

    planned_sessions = _get_sessions_in_range(db, athlete_id, week_start, week_end)
    week_activities = _get_activities_in_range(db, athlete_id, week_start, week_end)
    planned_count = analysis.planned_sessions if analysis and analysis.planned_sessions is not None else len(planned_sessions)
    completed_count = analysis.completed_sessions if analysis and analysis.completed_sessions is not None else len(week_activities)
    total_duration_minutes = (
        int(round((analysis.total_duration_sec or 0) / 60))
        if analysis and analysis.total_duration_sec is not None
        else _sum_duration_minutes(week_activities)
    )
    total_distance_km = (
        round((analysis.total_distance_m or 0) / 1000, 1)
        if analysis and analysis.total_distance_m is not None
        else _sum_distance_km(week_activities)
    )
    intensity_label = _weekly_intensity_label(analysis, total_duration_minutes, completed_count)
    summary_text = _build_weekly_dashboard_summary(
        planned_count=planned_count,
        completed_count=completed_count,
        intensity_label=intensity_label,
        analysis=analysis,
        unlinked_recent_count=_count_unlinked_recent_activities(db, athlete_id, reference_date),
    )
    return {
        "planned_count": planned_count,
        "completed_count": completed_count,
        "total_duration_minutes": total_duration_minutes,
        "total_duration_label": format_duration_minutes(total_duration_minutes),
        "total_distance_km": total_distance_km,
        "intensity_label": intensity_label,
        "summary": summary_text,
        "url": f"/analysis/weekly/{athlete_id}/{week_start.isoformat()}",
        "week_start": week_start,
        "week_end": week_end,
    }


def _get_sessions_for_date(db: Session, athlete_id: int, training_plan: TrainingPlan | None, reference_date: date) -> list[PlannedSession]:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.activity_match))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date == reference_date,
        )
        .order_by(PlannedSession.session_order.asc(), PlannedSession.id.asc())
    )
    if training_plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan.id)
    return list(db.scalars(statement).all())


def _get_next_session(db: Session, athlete_id: int, training_plan: TrainingPlan | None, reference_date: date) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date > reference_date,
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .limit(1)
    )
    if training_plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan.id)
    return db.scalar(statement)


def _get_today_activity(
    db: Session,
    athlete_id: int,
    reference_date: date,
    today_session: PlannedSession | None,
) -> dict[str, Any]:
    activities = _get_activities_in_range(db, athlete_id, reference_date, reference_date)
    if not activities:
        return {
            "activity": None,
            "is_linked": False,
            "has_analysis": False,
            "summary": "",
            "analysis_url": None,
            "detail_items": [],
            "link_status_label": "Pendiente",
            "analysis_status_label": "Pendiente",
            "execution_score_pct": None,
        }

    selected = None
    if today_session is not None:
        selected = next(
            (
                activity
                for activity in activities
                if activity.activity_match and activity.activity_match.planned_session_id_fk == today_session.id
            ),
            None,
        )
    if selected is None:
        selected = activities[-1]
    completed_analysis = _get_completed_activity_analysis(db, selected, today_session)
    has_analysis = completed_analysis is not None
    linked = selected.activity_match is not None
    analysis_url = _activity_analysis_url(selected, today_session)
    detail_items = _build_activity_detail_items(selected, completed_analysis)
    linked_session_name = (
        selected.activity_match.planned_session.name
        if selected.activity_match and selected.activity_match.planned_session is not None
        else None
    )
    summary = _build_activity_summary(
        selected,
        linked=linked,
        has_analysis=has_analysis,
        analysis=completed_analysis,
        linked_session_name=linked_session_name,
    )
    return {
        "activity": selected,
        "is_linked": linked,
        "has_analysis": has_analysis,
        "summary": summary,
        "analysis_url": analysis_url,
        "detail_items": detail_items,
        "link_status_label": f"Vinculada a {linked_session_name}" if linked and linked_session_name else ("Vinculada" if linked else "Sin vincular"),
            "analysis_status_label": "Analizada" if has_analysis else "Análisis pendiente",
            "execution_score_pct": _analysis_execution_score_pct(completed_analysis),
    }


def _get_health_metric_for_date(db: Session, athlete_id: int, reference_date: date) -> DailyHealthMetric | None:
    return db.scalar(
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date == reference_date,
        )
        .order_by(DailyHealthMetric.updated_at.desc(), DailyHealthMetric.id.desc())
    )


def _get_health_ai_for_date(db: Session, athlete_id: int, reference_date: date) -> HealthAiAnalysis | None:
    return db.scalar(
        select(HealthAiAnalysis)
        .where(
            HealthAiAnalysis.athlete_id == athlete_id,
            HealthAiAnalysis.reference_date == reference_date,
        )
        .order_by(HealthAiAnalysis.created_at.desc(), HealthAiAnalysis.id.desc())
    )


def _get_health_sync_state(db: Session, athlete_id: int) -> HealthSyncState | None:
    return db.scalar(
        select(HealthSyncState)
        .where(
            HealthSyncState.athlete_id == athlete_id,
            HealthSyncState.source == "garmin",
        )
        .order_by(HealthSyncState.updated_at.desc(), HealthSyncState.id.desc())
    )


def _get_sessions_in_range(db: Session, athlete_id: int, date_from: date, date_to: date) -> list[PlannedSession]:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= date_from,
            TrainingDay.day_date <= date_to,
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
    )
    return list(db.scalars(statement).all())


def _get_activities_in_range(db: Session, athlete_id: int, date_from: date, date_to: date) -> list[GarminActivity]:
    start_dt = datetime.combine(date_from - timedelta(days=1), time.min)
    end_dt = datetime.combine(date_to + timedelta(days=2), time.min)
    statement = (
        select(GarminActivity)
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
            selectinload(GarminActivity.session_analyses),
        )
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
            GarminActivity.start_time >= start_dt,
            GarminActivity.start_time < end_dt,
        )
        .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
    )
    activities = list(db.scalars(statement).all())
    return [activity for activity in activities if _activity_local_date(activity.start_time) and date_from <= _activity_local_date(activity.start_time) <= date_to]


def _activity_has_completed_analysis(db: Session, activity: GarminActivity, today_session: PlannedSession | None) -> bool:
    return _get_completed_activity_analysis(db, activity, today_session) is not None


def _activity_analysis_url(activity: GarminActivity, today_session: PlannedSession | None) -> str:
    if activity.activity_match and activity.activity_match.planned_session_id_fk:
        return f"/planned_sessions/{activity.activity_match.planned_session_id_fk}/analysis"
    if today_session is not None:
        return f"/planned_sessions/{today_session.id}/analysis"
    return f"/activities/{activity.id}"


def _count_unlinked_recent_activities(db: Session, athlete_id: int, reference_date: date) -> int:
    activities = _get_activities_in_range(db, athlete_id, reference_date - timedelta(days=6), reference_date)
    return sum(1 for activity in activities if activity.activity_match is None)


def _map_readiness_status(score: int | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 80:
        return "ready"
    if score >= 65:
        return "caution"
    if score >= 50:
        return "loaded"
    return "rest"


def _status_label(status: str) -> str:
    mapping = {
        "ready": "Listo para entrenar",
        "caution": "Bien, con control",
        "loaded": "Precaucion",
        "rest": "Conviene bajar carga",
        "insufficient_data": "Sin datos suficientes",
    }
    return mapping.get(status, "Sin datos suficientes")


def _default_status_summary(evaluation) -> str:
    if evaluation.reasons:
        return evaluation.reasons[0]
    return evaluation.recommendation


def _build_recommendation(
    *,
    status: str,
    today_session: PlannedSession | None,
    today_activity: GarminActivity | None,
    health_ai: HealthAiAnalysis | None,
) -> str:
    if today_activity is not None:
        return "Revisá el análisis y ajustá la próxima sesión si hace falta."
    if health_ai and health_ai.training_recommendation:
        return health_ai.training_recommendation
    if today_session is None:
        return "Día sin sesión planificada. Priorizá recuperación."
    if _is_demanding_session(today_session) and status in {"loaded", "rest"}:
        return "Conviene hacer la sesión más controlada o reducir intensidad."
    if not _is_demanding_session(today_session) and status in {"loaded", "rest"}:
        return "Podés mantenerla suave si las sensaciones acompañan."
    return "Mantené la sesión planificada y revisá sensaciones durante la entrada en calor."


def _activity_coach_summary(today_activity: dict[str, Any]) -> str:
    activity = today_activity["activity"]
    if activity is None:
        return ""
    return today_activity.get("summary") or (activity.activity_name or "Actividad")


def _post_activity_recommendation(
    *,
    next_session: dict[str, Any],
    weekly_summary: dict[str, Any],
    alerts: list[dict[str, Any]],
    status: str,
) -> str:
    if any(alert["title"] == "Cuidado con la intensidad" for alert in alerts):
        return "La próxima sesión pide control. Evitá sumar intensidad extra."
    if next_session["exists"] and _next_session_is_demanding(next_session) and status in {"loaded", "rest"}:
        return "Recuperá hoy y llegá fresco a la próxima sesión exigente."
    if next_session["exists"] and not _next_session_is_demanding(next_session):
        return "La próxima sesión puede mantenerse suave para asimilar la carga de hoy."
    if next_session["exists"]:
        return f"Revisá {next_session['title']} como siguiente paso del plan."
    if weekly_summary["intensity_label"] == "carga alta":
        return "Cerrá el día con recuperación y sin carga extra."
    return "Mantené la recuperación y revisá pendientes antes de la próxima carga."


def _planned_session_recommendation(
    *,
    score: int | None,
    status: str,
    today_session: dict[str, Any],
    next_session: dict[str, Any],
) -> str:
    if score is None:
        return "Sin datos de salud suficientes. Usá esta sesión con criterio y controlá sensaciones."
    if score >= 80:
        recommendation = "Podés hacer la sesión normal."
    elif score >= 65:
        recommendation = "Hacela con control y sin apurarte al inicio."
    elif score >= 50:
        recommendation = "Conviene reducir intensidad y mantenerla más controlada."
    else:
        recommendation = "Considerá cambiarla por regenerativo o descanso."

    if next_session["exists"] and _next_session_is_demanding(next_session) and status in {"loaded", "rest"}:
        recommendation = f"{recommendation} Además, evitá sumar intensidad extra antes de {next_session['title']}."
    return recommendation


def _planned_session_decision(score: int | None, next_session: dict[str, Any]) -> str:
    if score is None:
        return "Sincronizar salud antes de decidir."
    if score >= 80:
        return "Hacer la sesión como está planificada."
    if score >= 65:
        return "Hacer la sesión con control, sin forzar los bloques intensos."
    if next_session["exists"] and not _next_session_is_demanding(next_session):
        return "Mantener la próxima sesión suave y no sumar intensidad extra."
    return "Reducir intensidad o cambiar por regenerativo."


def _day_without_session_summary(weekly_summary: dict[str, Any], alerts: list[dict[str, Any]]) -> str:
    if any(alert["title"] == "Actividades sin vincular" for alert in alerts):
        return "No hay trabajo planificado hoy, pero quedan pendientes por revisar."
    if weekly_summary["completed_count"] and weekly_summary["planned_count"]:
        return (
            f"Semana en curso: {weekly_summary['completed_count']} de "
            f"{weekly_summary['planned_count']} sesiones ya resueltas."
        )
    return "Día libre dentro del plan actual."


def _sport_text(value: str | None) -> str:
    mapping = {
        "running": "Running",
        "cycling": "Cycling",
        "swimming": "Swimming",
        "strength": "Strength",
        "walking": "Walking",
        "mtb": "MTB",
        "trail_running": "Trail",
        "multisport": "Multisport",
    }
    if not value:
        return ""
    return mapping.get(str(value).strip().lower(), str(value).strip().capitalize())


def _next_session_is_demanding(next_session: dict[str, Any]) -> bool:
    session = next_session.get("session")
    if session is None:
        return False
    return _is_demanding_session(session)


def _is_demanding_session(session: PlannedSession) -> bool:
    session_type = (session.session_type or "").strip().lower()
    if session.is_key_session or session_type in {"tempo", "hard", "intervals", "race"}:
        return True
    objective_text = " ".join(part for part in (session.name, session.description_text, session.target_notes) if part).lower()
    demanding_tokens = ("tempo", "series", "interval", "fuerte", "race", "umbral", "vo2", "z4", "z5")
    return any(token in objective_text for token in demanding_tokens)


def _weekly_intensity_label(analysis: WeeklyAnalysis | None, total_duration_minutes: int | None, completed_count: int) -> str:
    if analysis is not None and analysis.load_score is not None:
        if analysis.load_score >= 80:
            return "carga alta"
        if analysis.load_score >= 55:
            return "carga moderada"
        return "carga baja"
    if total_duration_minutes is None or completed_count == 0:
        return "sin datos suficientes"
    if total_duration_minutes >= 420:
        return "carga alta"
    if total_duration_minutes >= 180:
        return "carga moderada"
    return "carga baja"


def _duration_minutes_label(duration_sec: int | None) -> str:
    if not duration_sec:
        return ""
    total_minutes = int(round(duration_sec / 60))
    return format_duration_minutes(total_minutes)


def _distance_km_label(distance_m: float | None) -> str:
    if distance_m is None:
        return ""
    return f"{distance_m / 1000:.1f} km" if distance_m >= 1000 else f"{int(round(distance_m))} m"


def _sum_duration_minutes(activities: list[GarminActivity]) -> int | None:
    values = [activity.duration_sec for activity in activities if activity.duration_sec]
    if not values:
        return None
    return int(round(sum(values) / 60))


def _sum_distance_km(activities: list[GarminActivity]) -> float | None:
    values = [activity.distance_m for activity in activities if activity.distance_m is not None]
    if not values:
        return None
    return round(sum(values) / 1000, 1)


def _calendar_url(training_plan: TrainingPlan | None, selected_date: date) -> str:
    if training_plan is None:
        return "/calendar"
    return (
        f"/training_plans/{training_plan.id}/calendar"
        f"?selected_date={selected_date.isoformat()}&month={selected_date.strftime('%Y-%m')}&athlete_id={training_plan.athlete_id}"
    )


def _main_limiter_label(value: str | None) -> str | None:
    mapping = {
        "hrv": "HRV",
        "resting_hr": "FC reposo",
        "sleep": "Sueno",
        "body_battery": "Body Battery",
        "stress": "Estres",
    }
    return mapping.get(value or "")


def _activity_local_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone(APP_LOCAL_TIMEZONE).date()


def _get_completed_activity_analysis(
    db: Session,
    activity: GarminActivity,
    today_session: PlannedSession | None,
) -> SessionAnalysis | None:
    completed = [analysis for analysis in activity.session_analyses if analysis.status.startswith("completed")]
    if completed:
        completed.sort(key=lambda item: ((item.analyzed_at or datetime.min.replace(tzinfo=timezone.utc)), item.id), reverse=True)
        return completed[0]
    if today_session is None:
        return None
    return db.scalar(
        select(SessionAnalysis)
        .where(
            SessionAnalysis.activity_id == activity.id,
            SessionAnalysis.planned_session_id == today_session.id,
            SessionAnalysis.status.like("completed%"),
        )
        .order_by(SessionAnalysis.analyzed_at.desc(), SessionAnalysis.id.desc())
    )


def _build_activity_detail_items(activity: GarminActivity, analysis: SessionAnalysis | None) -> list[str]:
    parts: list[str] = []
    sport_label = _sport_text(activity.sport_type)
    if sport_label:
        parts.append(sport_label)
    duration = _duration_minutes_label(activity.duration_sec)
    if duration:
        parts.append(duration)
    distance = _distance_km_label(activity.distance_m)
    if distance:
        parts.append(distance)
    if activity.avg_hr is not None:
        parts.append(f"FC media {activity.avg_hr} ppm")
    if activity.training_load is not None:
        parts.append(f"Load {int(round(activity.training_load))}")
    execution_score_pct = _analysis_execution_score_pct(analysis)
    if execution_score_pct is not None:
        parts.append(f"Score {execution_score_pct}%")
    return parts


def _build_activity_summary(
    activity: GarminActivity,
    *,
    linked: bool,
    has_analysis: bool,
    analysis: SessionAnalysis | None,
    linked_session_name: str | None,
) -> str:
    parts = _build_activity_detail_items(activity, analysis)
    if linked and linked_session_name:
        parts.append(f"Vinculada a {linked_session_name}")
    elif linked:
        parts.append("Vinculada")
    else:
        parts.append("Sin vincular")
    parts.append("Analizada" if has_analysis else "Analisis pendiente")
    return " · ".join(parts) if parts else (activity.activity_name or "Actividad")


def _analysis_execution_score_pct(analysis: SessionAnalysis | None) -> int | None:
    if analysis is None or analysis.execution_score is None:
        return None
    return int(round(analysis.execution_score))


def _build_dashboard_health_summary(
    metric: DailyHealthMetric,
    health_ai: HealthAiAnalysis | None,
    readiness_label: str,
    limiter_label: str | None,
) -> str:
    ai_summary = _trim_dashboard_health_text(health_ai.summary if health_ai and health_ai.summary else None)
    if ai_summary:
        return ai_summary

    metric_parts: list[str] = []
    if metric.sleep_hours is not None:
        metric_parts.append(f"Sueño {metric.sleep_hours:.1f} h")
    hrv_value = metric.hrv_value or metric.hrv_avg_ms
    if hrv_value is not None:
        metric_parts.append(f"HRV {int(round(hrv_value))}")
    body_battery = metric.body_battery_morning or metric.body_battery_start
    if body_battery is not None:
        metric_parts.append(f"Body Battery {body_battery}")

    intro = f"Readiness {readiness_label.lower()}."
    if metric_parts:
        action = "Mantener control." if limiter_label else "Carga del dia clara."
        return f"{intro} " + ", ".join(metric_parts) + f"; {action}"
    if limiter_label:
        return f"{intro} El punto a cuidar hoy es {limiter_label.lower()}."
    return intro


def _trim_dashboard_health_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = " ".join(value.split())
    sentences: list[str] = []
    buffer = ""
    for char in normalized:
        buffer += char
        if char in ".!?":
            cleaned = buffer.strip()
            if cleaned:
                sentences.append(cleaned)
            buffer = ""
        if len(sentences) == 2:
            break
    if len(sentences) < 2 and buffer.strip():
        sentences.append(buffer.strip())
    trimmed = " ".join(sentences[:2]).strip()
    if len(trimmed) > 170:
        trimmed = trimmed[:167].rstrip(" ,;") + "..."
    return trimmed


def _decision_from_recommendation(value: str) -> str:
    trimmed = " ".join(value.split()).strip()
    if not trimmed:
        return "Revisar el dia antes de decidir."
    if len(trimmed) <= 95:
        return trimmed
    short = trimmed.split(".")[0].strip()
    return (short + ".") if short else "Revisar el dia antes de decidir."


def _post_activity_decision(*, next_session: dict[str, Any], status: str) -> str:
    if next_session["exists"] and not _next_session_is_demanding(next_session):
        return "Mantener la próxima sesión suave y no sumar intensidad extra."
    if next_session["exists"] and _next_session_is_demanding(next_session) and status in {"loaded", "rest"}:
        return "Priorizar recuperación y no agregar carga hoy."
    return "Priorizar recuperación y no agregar carga hoy."


def _build_weekly_dashboard_summary(
    *,
    planned_count: int,
    completed_count: int,
    intensity_label: str,
    analysis: WeeklyAnalysis | None,
    unlinked_recent_count: int,
) -> str:
    if analysis and analysis.summary_short:
        return _trim_dashboard_health_text(analysis.summary_short)
    if completed_count == 0:
        if unlinked_recent_count > 0:
            return "Semana con poca carga registrada. Revisá si faltan actividades por vincular."
        return "Semana con poca carga registrada. Conviene confirmar si ya hubo actividad."
    adherence_ratio = (completed_count / planned_count) if planned_count else 0
    if intensity_label == "carga alta":
        return "Semana desbalanceada: conviene recuperar antes de volver a intensidades altas."
    if intensity_label == "carga moderada" and adherence_ratio >= 0.7:
        return "Carga moderada y buena adherencia. Evitá sumar intensidad no planificada."
    if intensity_label == "carga baja":
        return "Semana bien encaminada. Mantener las próximas sesiones suaves para asimilar la carga."
    return "Semana en curso. Sostener el plan y revisar la recuperación antes de apretar."
