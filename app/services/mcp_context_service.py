from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.goal import Goal
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.services.analysis_v2.session_analysis_service import ANALYSIS_VERSION as SESSION_ANALYSIS_VERSION
from app.services.analysis_v2.weekly_analysis_service import (
    ANALYSIS_VERSION as WEEKLY_ANALYSIS_VERSION,
    build_week_context,
    compute_week_metrics,
)
from app.services.dashboard_service import build_dashboard_context
from app.services.health_readiness_service import (
    build_health_readiness_summary,
    build_health_training_context,
    evaluate_health_readiness,
)


def build_session_feedback_payload(
    db: Session,
    *,
    athlete,
    training_plan: TrainingPlan | None,
    target_date: date,
) -> dict[str, Any]:
    planned_session = _get_session_for_date(db, athlete.id, training_plan, target_date)
    completed_activity = _get_activity_for_date(db, athlete.id, target_date, planned_session)
    analysis = _get_relevant_analysis(db, planned_session, completed_activity)
    next_session = _get_next_session(db, athlete.id, training_plan, target_date)
    week_context = _build_week_context_summary(db, athlete.id, target_date)
    dashboard = build_dashboard_context(db, athlete, training_plan, selected_date=target_date)

    return {
        "schema_version": "mcp_session_feedback_v1",
        "date": target_date.isoformat(),
        "athlete": _serialize_athlete(athlete),
        "current_goal": _serialize_goal(_resolve_current_goal(training_plan, planned_session)),
        "planned_session": _serialize_planned_session(planned_session),
        "completed_activity": _serialize_activity(completed_activity),
        "analysis": _serialize_session_analysis(analysis),
        "week_context": week_context,
        "next_session": _serialize_planned_session(next_session),
        "decision": _build_decision_payload(
            dashboard=dashboard,
            analysis=analysis,
            next_session=next_session,
        ),
    }


def build_week_context_payload(
    db: Session,
    *,
    athlete,
    training_plan: TrainingPlan | None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    selected_date = reference_date or date.today()
    context = build_week_context(db, athlete.id, selected_date)
    metrics = compute_week_metrics(context)
    weekly_analysis = _get_latest_weekly_analysis(db, athlete.id, context.week_start_date)
    planned_sessions = _get_sessions_in_range(db, athlete.id, context.week_start_date, context.week_end_date, training_plan)
    activities = _get_activities_in_range(db, athlete.id, context.week_start_date, context.week_end_date)
    readiness_summary = _build_readiness_summary_payload(db, athlete.id, context.week_end_date)
    derived_flags = metrics.get("derived_flags", {})
    recommendation = (
        weekly_analysis.next_week_recommendation
        if weekly_analysis and weekly_analysis.next_week_recommendation
        else _fallback_week_recommendation(derived_flags)
    )

    return {
        "schema_version": "mcp_week_context_v1",
        "athlete": _serialize_athlete(athlete),
        "week_start_date": context.week_start_date.isoformat(),
        "week_end_date": context.week_end_date.isoformat(),
        "current_goal": _serialize_goal(_resolve_current_goal(training_plan, planned_sessions[0] if planned_sessions else None)),
        "planned_sessions": [_serialize_planned_session(item) for item in planned_sessions],
        "completed_activities": [_serialize_activity(item) for item in activities],
        "weekly_load_summary": _build_weekly_load_summary(metrics),
        "intensity_distribution": metrics.get("distribution", {}).get("intensity_zone_summary"),
        "readiness_summary": readiness_summary,
        "main_warning": _build_week_main_warning(derived_flags),
        "recommendation": recommendation,
    }


def build_last_activity_feedback_payload(
    db: Session,
    *,
    athlete,
    training_plan: TrainingPlan | None,
) -> dict[str, Any]:
    del training_plan
    activity = _get_last_activity(db, athlete.id)
    linked_planned_session = (
        activity.activity_match.planned_session
        if activity and activity.activity_match and activity.activity_match.planned_session is not None
        else None
    )
    analysis = _get_relevant_analysis(db, linked_planned_session, activity)
    recommendation = (
        analysis.next_recommendation
        if analysis and analysis.next_recommendation
        else "No hay actividad reciente para revisar."
        if activity is None
        else "La actividad existe, pero todavia no tiene analisis disponible."
    )

    return {
        "schema_version": "mcp_last_activity_feedback_v1",
        "athlete": _serialize_athlete(athlete),
        "completed_activity": _serialize_activity(activity),
        "linked_planned_session": _serialize_planned_session(linked_planned_session),
        "analysis": _serialize_session_analysis(analysis),
        "recommendation": recommendation,
    }


def build_next_session_context_payload(
    db: Session,
    *,
    athlete,
    training_plan: TrainingPlan | None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    selected_date = reference_date or date.today()
    dashboard = build_dashboard_context(db, athlete, training_plan, selected_date=selected_date)
    next_session = _get_next_session(db, athlete.id, training_plan, selected_date)
    readiness_today = _build_readiness_summary_payload(db, athlete.id, selected_date)
    recent_training_load = build_health_training_context(db, athlete.id, selected_date)

    recommendation = (
        "No hay proxima sesion planificada."
        if next_session is None
        else dashboard.get("today_status", {}).get("recommendation")
        or "Usa el contexto reciente para decidir si mantener la proxima sesion."
    )

    return {
        "schema_version": "mcp_next_session_context_v1",
        "athlete": _serialize_athlete(athlete),
        "readiness_today": readiness_today,
        "recent_training_load": recent_training_load,
        "next_session": _serialize_planned_session(next_session),
        "current_goal": _serialize_goal(_resolve_current_goal(training_plan, next_session)),
        "recommendation": recommendation,
    }


def _get_session_for_date(
    db: Session,
    athlete_id: int,
    training_plan: TrainingPlan | None,
    target_date: date,
) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity),
        )
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date == target_date,
        )
        .order_by(PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .limit(1)
    )
    if training_plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan.id)
    return db.scalar(statement)


def _get_next_session(
    db: Session,
    athlete_id: int,
    training_plan: TrainingPlan | None,
    target_date: date,
) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date > target_date,
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .limit(1)
    )
    if training_plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan.id)
    return db.scalar(statement)


def _get_activity_for_date(
    db: Session,
    athlete_id: int,
    target_date: date,
    planned_session: PlannedSession | None,
) -> GarminActivity | None:
    if planned_session and planned_session.activity_match and planned_session.activity_match.garmin_activity:
        return planned_session.activity_match.garmin_activity

    activities = _get_activities_in_range(db, athlete_id, target_date, target_date)
    if not activities:
        return None

    if planned_session is not None:
        compatible = [
            item
            for item in activities
            if _normalized(item.sport_type) == _normalized(planned_session.sport_type)
        ]
        if compatible:
            return compatible[-1]
    return activities[-1]


def _get_last_activity(db: Session, athlete_id: int) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
            selectinload(GarminActivity.session_analyses),
        )
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .limit(1)
    )


def _get_activities_in_range(
    db: Session,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> list[GarminActivity]:
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
    return [
        item
        for item in activities
        if _activity_local_date(item) is not None and date_from <= _activity_local_date(item) <= date_to
    ]


def _get_sessions_in_range(
    db: Session,
    athlete_id: int,
    date_from: date,
    date_to: date,
    training_plan: TrainingPlan | None,
) -> list[PlannedSession]:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= date_from,
            TrainingDay.day_date <= date_to,
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
    )
    if training_plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan.id)
    return list(db.scalars(statement).all())


def _get_relevant_analysis(
    db: Session,
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
) -> SessionAnalysis | None:
    if activity is None and planned_session is None:
        return None

    statement = (
        select(SessionAnalysis)
        .where(SessionAnalysis.analysis_version == SESSION_ANALYSIS_VERSION)
        .order_by(SessionAnalysis.analyzed_at.desc(), SessionAnalysis.id.desc())
    )
    if activity is not None:
        statement = statement.where(SessionAnalysis.activity_id == activity.id)
    if planned_session is not None:
        statement = statement.where(SessionAnalysis.planned_session_id == planned_session.id)
    return db.scalar(statement.limit(1))


def _get_latest_weekly_analysis(db: Session, athlete_id: int, week_start_date: date) -> WeeklyAnalysis | None:
    return db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start_date,
            WeeklyAnalysis.analysis_version == WEEKLY_ANALYSIS_VERSION,
        )
        .order_by(WeeklyAnalysis.analyzed_at.desc(), WeeklyAnalysis.id.desc())
    )


def _resolve_current_goal(training_plan: TrainingPlan | None, planned_session: PlannedSession | None) -> Goal | None:
    if training_plan is not None and training_plan.goal is not None:
        return training_plan.goal
    if planned_session and planned_session.training_day and planned_session.training_day.training_plan:
        return planned_session.training_day.training_plan.goal
    return None


def _build_week_context_summary(db: Session, athlete_id: int, target_date: date) -> dict[str, Any]:
    context = build_week_context(db, athlete_id, target_date)
    metrics = compute_week_metrics(context)
    totals = metrics.get("totals", {})
    compliance = metrics.get("compliance", {})
    distribution = metrics.get("distribution", {})

    return {
        "week_start_date": context.week_start_date.isoformat(),
        "week_end_date": context.week_end_date.isoformat(),
        "planned_sessions": compliance.get("planned_sessions"),
        "completed_sessions": compliance.get("completed_sessions"),
        "compliance_ratio_pct": compliance.get("compliance_ratio_pct"),
        "total_duration_sec": totals.get("total_duration_sec"),
        "total_distance_m": totals.get("total_distance_m"),
        "activity_count": totals.get("activity_count"),
        "intensity_distribution": distribution.get("intensity_zone_summary"),
        "main_warning": _build_week_main_warning(metrics.get("derived_flags", {})),
    }


def _build_weekly_load_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    totals = metrics.get("totals", {})
    compliance = metrics.get("compliance", {})
    scores = metrics.get("scores", {})
    return {
        "activity_count": totals.get("activity_count"),
        "total_duration_sec": totals.get("total_duration_sec"),
        "total_distance_m": totals.get("total_distance_m"),
        "total_elevation_gain_m": totals.get("total_elevation_gain_m"),
        "planned_sessions": compliance.get("planned_sessions"),
        "completed_sessions": compliance.get("completed_sessions"),
        "compliance_ratio_pct": compliance.get("compliance_ratio_pct"),
        "load_score": scores.get("load_score"),
        "consistency_score": scores.get("consistency_score"),
        "fatigue_score": scores.get("fatigue_score"),
        "balance_score": scores.get("balance_score"),
    }


def _build_readiness_summary_payload(db: Session, athlete_id: int, target_date: date) -> dict[str, Any] | None:
    metric = db.scalar(
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date == target_date,
        )
        .order_by(DailyHealthMetric.updated_at.desc(), DailyHealthMetric.id.desc())
    )
    if metric is None:
        return None

    summary = build_health_readiness_summary(db, athlete_id, target_date)
    evaluation = evaluate_health_readiness(summary)
    ai = db.scalar(
        select(HealthAiAnalysis)
        .where(
            HealthAiAnalysis.athlete_id == athlete_id,
            HealthAiAnalysis.reference_date == target_date,
        )
        .order_by(HealthAiAnalysis.created_at.desc(), HealthAiAnalysis.id.desc())
    )
    return {
        "reference_date": target_date.isoformat(),
        "readiness_score": evaluation.readiness_score,
        "readiness_status": evaluation.readiness_status,
        "readiness_label": evaluation.readiness_label,
        "main_limiter": evaluation.main_limiter,
        "reasons": evaluation.reasons,
        "recommendation": ai.training_recommendation if ai and ai.training_recommendation else evaluation.recommendation,
    }


def _build_decision_payload(
    *,
    dashboard: dict[str, Any],
    analysis: SessionAnalysis | None,
    next_session: PlannedSession | None,
) -> dict[str, Any]:
    recommendation = dashboard.get("today_status", {}).get("recommendation") or "Mantener segun sensaciones."
    reason = (
        analysis.next_recommendation
        if analysis and analysis.next_recommendation
        else dashboard.get("today_status", {}).get("decision")
        or recommendation
    )
    modify = _text_suggests_modification(reason) or _text_suggests_modification(recommendation)
    keep = not modify
    if next_session is None:
        keep = True
        modify = False

    return {
        "keep_plan": keep,
        "modify_next_session": modify,
        "suggested_change": recommendation if modify else None,
        "reason": reason,
    }


def _build_week_main_warning(flags: dict[str, Any]) -> str | None:
    if flags.get("overload_flag"):
        return "La semana muestra senales de sobrecarga."
    if flags.get("high_fatigue_risk_flag"):
        return "La fatiga semanal aparece elevada."
    if flags.get("poor_distribution_flag"):
        return "La carga semanal quedo demasiado concentrada."
    if flags.get("intensity_distribution_imbalance_flag"):
        return "La distribucion de intensidad se ve desbalanceada."
    if flags.get("undertraining_flag"):
        return "La carga semanal quedo por debajo de lo habitual."
    return None


def _fallback_week_recommendation(flags: dict[str, Any]) -> str:
    if flags.get("overload_flag") or flags.get("high_fatigue_risk_flag"):
        return "Conviene bajar un poco la carga y priorizar recuperacion."
    if flags.get("poor_distribution_flag") or flags.get("intensity_distribution_imbalance_flag"):
        return "Conviene ordenar mejor la distribucion de carga e intensidad."
    if flags.get("undertraining_flag"):
        return "La semana parece liviana; revisar si el plan quedo corto o incompleto."
    return "La semana viene estable; mantener el plan con seguimiento de sensaciones."


def _serialize_athlete(athlete) -> dict[str, Any]:
    return {
        "id": athlete.id,
        "name": athlete.name,
    }


def _serialize_goal(goal: Goal | None) -> dict[str, Any] | None:
    if goal is None:
        return None
    return {
        "id": goal.id,
        "name": goal.name,
        "sport_type": goal.sport_type,
        "event_type": goal.event_type,
        "event_date": goal.event_date.isoformat() if goal.event_date else None,
        "distance_km": goal.distance_km,
    }


def _serialize_planned_session(session: PlannedSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    return {
        "id": session.id,
        "date": session.training_day.day_date.isoformat() if session.training_day and session.training_day.day_date else None,
        "training_plan_id": session.training_day.training_plan.id if session.training_day and session.training_day.training_plan else None,
        "name": session.name,
        "sport_type": session.sport_type,
        "session_type": session.session_type,
        "description": session.description_text,
        "target_notes": session.target_notes,
        "expected_duration_min": session.expected_duration_min,
        "expected_distance_km": session.expected_distance_km,
        "expected_elevation_gain_m": session.expected_elevation_gain_m,
        "target_type": session.target_type,
        "target_hr_zone": session.target_hr_zone,
        "target_pace_zone": session.target_pace_zone,
        "target_power_zone": session.target_power_zone,
        "target_rpe_zone": session.target_rpe_zone,
        "is_key_session": session.is_key_session,
    }


def _serialize_activity(activity: GarminActivity | None) -> dict[str, Any] | None:
    if activity is None:
        return None
    return {
        "id": activity.id,
        "garmin_activity_id": activity.garmin_activity_id,
        "date": _activity_local_date(activity).isoformat() if _activity_local_date(activity) else None,
        "start_time": activity.start_time.isoformat() if activity.start_time else None,
        "name": activity.activity_name,
        "sport_type": activity.sport_type,
        "duration_sec": activity.duration_sec,
        "distance_m": activity.distance_m,
        "elevation_gain_m": activity.elevation_gain_m,
        "avg_hr": activity.avg_hr,
        "avg_power": activity.avg_power,
        "avg_pace_sec_km": activity.avg_pace_sec_km,
        "training_load": activity.training_load,
        "training_effect_aerobic": activity.training_effect_aerobic,
        "training_effect_anaerobic": activity.training_effect_anaerobic,
        "linked_planned_session_id": activity.activity_match.planned_session_id_fk if activity.activity_match else None,
    }


def _serialize_session_analysis(analysis: SessionAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "status": analysis.status,
        "analysis_version": analysis.analysis_version,
        "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
        "summary_short": analysis.summary_short,
        "coach_conclusion": analysis.coach_conclusion,
        "next_recommendation": analysis.next_recommendation,
        "compliance_score": analysis.compliance_score,
        "execution_score": analysis.execution_score,
        "control_score": analysis.control_score,
        "fatigue_score": analysis.fatigue_score,
        "llm_json": analysis.llm_json,
    }


def _activity_local_date(activity: GarminActivity) -> date | None:
    if activity.start_time is None:
        return None
    if activity.start_time.tzinfo is not None:
        return activity.start_time.astimezone().date()
    return activity.start_time.date()


def _normalized(value: str | None) -> str:
    return (value or "").strip().lower()


def _text_suggests_modification(value: str | None) -> bool:
    normalized = _normalized(value)
    return any(
        token in normalized
        for token in (
            "reduc",
            "descanso",
            "regenerativo",
            "recuper",
            "cambiar",
            "controlada",
            "suave",
            "bajar",
            "evita",
        )
    )
