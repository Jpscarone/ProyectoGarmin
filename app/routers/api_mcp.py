from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.analysis_report import AnalysisReport
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.db.session import get_db
from app.services.athlete_context import get_current_athlete, get_current_training_plan
from app.services.mcp_context_service import (
    build_last_activity_feedback_payload,
    build_next_session_context_payload,
    build_session_feedback_payload,
    build_week_context_payload,
)
from app.services.mcp_security import verify_mcp_bearer_token
from app.services.training_plan_service import select_default_training_plan


router = APIRouter(
    prefix="/api/mcp",
    tags=["api_mcp"],
    dependencies=[Depends(verify_mcp_bearer_token)],
)


@router.get("/ping")
def read_mcp_ping() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
    }


@router.get("/athletes")
def list_mcp_athletes(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    athletes = list(
        db.scalars(
            select(Athlete)
            .order_by(Athlete.name.asc(), Athlete.id.asc())
        ).all()
    )
    return [
        {
            "id": athlete.id,
            "name": athlete.name,
            "status": athlete.status,
        }
        for athlete in athletes
    ]


@router.get("/activities/recent")
def list_recent_activities(
    athlete_id: int = Query(...),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    activities = list(
        db.scalars(
            select(GarminActivity)
            .where(GarminActivity.athlete_id == athlete.id)
            .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
            .limit(limit)
        ).all()
    )
    return {
        "athlete": _serialize_athlete_min(athlete),
        "count": len(activities),
        "activities": [_serialize_activity_recent(item) for item in activities],
    }


@router.get("/activities/{activity_id}")
def read_activity_detail(
    activity_id: int,
    athlete_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    activity = db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.id == activity_id,
            GarminActivity.athlete_id == athlete.id,
        )
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
            selectinload(GarminActivity.session_analyses),
            selectinload(GarminActivity.analysis_reports),
        )
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")

    latest_session_analysis = _latest_completed_session_analysis(activity.session_analyses)
    latest_analysis_report = _latest_analysis_report(activity.analysis_reports)

    return {
        "athlete": _serialize_athlete_min(athlete),
        "activity": _serialize_activity_detail(activity),
        "linked_planned_session": _serialize_linked_planned_session(activity),
        "session_analysis_summary": _serialize_session_analysis_summary(latest_session_analysis),
        "analysis_report_summary": _serialize_analysis_report_summary(latest_analysis_report),
    }


@router.get("/health/summary")
def read_health_summary(
    athlete_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    latest_metric = db.scalar(
        select(DailyHealthMetric)
        .where(DailyHealthMetric.athlete_id == athlete.id)
        .order_by(DailyHealthMetric.metric_date.desc(), DailyHealthMetric.id.desc())
    )
    recent_metrics = list(
        db.scalars(
            select(DailyHealthMetric)
            .where(DailyHealthMetric.athlete_id == athlete.id)
            .order_by(DailyHealthMetric.metric_date.desc(), DailyHealthMetric.id.desc())
            .limit(7)
        ).all()
    )
    latest_ai_analysis = db.scalar(
        select(HealthAiAnalysis)
        .where(HealthAiAnalysis.athlete_id == athlete.id)
        .order_by(HealthAiAnalysis.reference_date.desc(), HealthAiAnalysis.created_at.desc(), HealthAiAnalysis.id.desc())
    )
    return {
        "athlete": _serialize_athlete_min(athlete),
        "latest_daily_health_metric": _serialize_daily_health_metric(latest_metric),
        "recent_daily_health_metrics": [_serialize_daily_health_metric(item) for item in recent_metrics],
        "latest_health_ai_analysis": _serialize_health_ai_analysis(latest_ai_analysis),
    }


@router.get("/weekly/latest")
def read_latest_weekly_analysis(
    athlete_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    latest_weekly = db.scalar(
        select(WeeklyAnalysis)
        .where(WeeklyAnalysis.athlete_id == athlete.id)
        .order_by(WeeklyAnalysis.week_start_date.desc(), WeeklyAnalysis.id.desc())
    )
    return {
        "athlete": _serialize_athlete_min(athlete),
        "weekly_analysis": _serialize_weekly_analysis(latest_weekly),
    }


@router.get("/training/status")
def read_training_status(
    athlete_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    plan = select_default_training_plan(db, athlete_id=athlete.id, today=date.today())
    next_session = _get_next_planned_session(db, athlete.id, plan)
    last_activity = _get_latest_activity(db, athlete.id)
    latest_metric = _get_latest_daily_health_metric(db, athlete.id)
    latest_ai_analysis = _get_latest_health_ai_analysis(db, athlete.id)
    latest_weekly = _get_latest_weekly_analysis(db, athlete.id)

    return {
        "athlete": _serialize_athlete_min(athlete),
        "active_or_latest_plan": _serialize_training_plan(plan),
        "next_planned_session": _serialize_planned_session(next_session),
        "latest_activity": _serialize_activity_recent(last_activity) if last_activity is not None else None,
        "latest_readiness": {
            "daily_health_metric": _serialize_daily_health_metric(latest_metric),
            "health_ai_analysis": _serialize_health_ai_analysis(latest_ai_analysis),
        },
        "latest_weekly_analysis": _serialize_weekly_analysis(latest_weekly),
    }


@router.get("/session-feedback")
def read_session_feedback(
    request: Request,
    date_value: str = Query(alias="date"),
    athlete_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    target_date = _parse_iso_date(date_value, "date")
    athlete = _resolve_context_athlete(request, db, athlete_id=athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_session_feedback_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
        target_date=target_date,
    )


@router.get("/week-context")
def read_week_context(
    request: Request,
    athlete_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    athlete = _resolve_context_athlete(request, db, athlete_id=athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_week_context_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
    )


@router.get("/last-activity-feedback")
def read_last_activity_feedback(
    request: Request,
    athlete_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    athlete = _resolve_context_athlete(request, db, athlete_id=athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_last_activity_feedback_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
    )


@router.get("/next-session-context")
def read_next_session_context(
    request: Request,
    athlete_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    athlete = _resolve_context_athlete(request, db, athlete_id=athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_next_session_context_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
    )


def _parse_iso_date(raw_value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} debe tener formato YYYY-MM-DD.",
        ) from exc


def _resolve_context_athlete(request: Request, db: Session, *, athlete_id: int | None) -> Athlete | None:
    if athlete_id is not None:
        athlete = db.get(Athlete, athlete_id)
        if athlete is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
        return athlete
    return get_current_athlete(request, db)


def _get_athlete_or_404(db: Session, athlete_id: int) -> Athlete:
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    return athlete


def _serialize_athlete_min(athlete: Athlete) -> dict[str, Any]:
    return {
        "id": athlete.id,
        "name": athlete.name,
        "status": athlete.status,
    }


def _serialize_activity_recent(activity: GarminActivity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "garmin_activity_id": activity.garmin_activity_id,
        "activity_name": activity.activity_name,
        "sport_type": activity.sport_type,
        "start_time": activity.start_time.isoformat() if activity.start_time else None,
        "duration_sec": activity.duration_sec,
        "distance_m": activity.distance_m,
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "training_load": activity.training_load,
        "training_effect_aerobic": activity.training_effect_aerobic,
        "training_effect_anaerobic": activity.training_effect_anaerobic,
    }


def _serialize_activity_detail(activity: GarminActivity) -> dict[str, Any]:
    return {
        **_serialize_activity_recent(activity),
        "end_time": activity.end_time.isoformat() if activity.end_time else None,
        "moving_duration_sec": activity.moving_duration_sec,
        "elevation_gain_m": activity.elevation_gain_m,
        "elevation_loss_m": activity.elevation_loss_m,
        "avg_power": activity.avg_power,
        "max_power": activity.max_power,
        "normalized_power": activity.normalized_power,
        "avg_speed_mps": activity.avg_speed_mps,
        "avg_pace_sec_km": activity.avg_pace_sec_km,
        "avg_cadence": activity.avg_cadence,
        "max_cadence": activity.max_cadence,
        "calories": activity.calories,
        "avg_temperature_c": activity.avg_temperature_c,
        "device_name": activity.device_name,
    }


def _serialize_linked_planned_session(activity: GarminActivity) -> dict[str, Any] | None:
    match = activity.activity_match
    planned = match.planned_session if match is not None and getattr(match, "planned_session", None) is not None else None
    if planned is None:
        return None
    return {
        "id": planned.id,
        "name": planned.name,
        "date": planned.training_day.day_date.isoformat() if planned.training_day and planned.training_day.day_date else None,
        "session_type": planned.session_type,
        "sport_type": planned.sport_type,
    }


def _latest_completed_session_analysis(analyses: list[SessionAnalysis]) -> SessionAnalysis | None:
    completed = [item for item in analyses if (item.status or "").startswith("completed")]
    if completed:
        return sorted(
            completed,
            key=lambda item: (item.analyzed_at or item.created_at, item.id),
            reverse=True,
        )[0]
    if analyses:
        return sorted(
            analyses,
            key=lambda item: (item.analyzed_at or item.created_at, item.id),
            reverse=True,
        )[0]
    return None


def _latest_analysis_report(reports: list[AnalysisReport]) -> AnalysisReport | None:
    if not reports:
        return None
    return sorted(
        reports,
        key=lambda item: (item.generated_at or item.created_at, item.id),
        reverse=True,
    )[0]


def _serialize_session_analysis_summary(analysis: SessionAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "status": analysis.status,
        "analysis_version": analysis.analysis_version,
        "summary_short": analysis.summary_short,
        "coach_conclusion": analysis.coach_conclusion,
        "next_recommendation": analysis.next_recommendation,
        "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
    }


def _serialize_analysis_report_summary(report: AnalysisReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "id": report.id,
        "report_type": report.report_type,
        "title": report.title,
        "overall_score": report.overall_score,
        "overall_status": report.overall_status,
        "summary_text": report.summary_text,
        "recommendation_text": report.recommendation_text,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
    }


def _serialize_daily_health_metric(metric: DailyHealthMetric | None) -> dict[str, Any] | None:
    if metric is None:
        return None
    return {
        "id": metric.id,
        "metric_date": metric.metric_date.isoformat(),
        "sleep_duration_minutes": metric.sleep_duration_minutes,
        "sleep_hours": metric.sleep_hours,
        "sleep_score": metric.sleep_score,
        "stress_avg": metric.stress_avg,
        "body_battery_morning": metric.body_battery_morning,
        "body_battery_start": metric.body_battery_start,
        "body_battery_end": metric.body_battery_end,
        "hrv_status": metric.hrv_status,
        "hrv_value": metric.hrv_value,
        "hrv_avg_ms": metric.hrv_avg_ms,
        "resting_hr": metric.resting_hr,
        "training_load": metric.training_load,
        "recovery_time_hours": metric.recovery_time_hours,
        "vo2max": metric.vo2max,
        "source": metric.source,
    }


def _serialize_health_ai_analysis(analysis: HealthAiAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "reference_date": analysis.reference_date.isoformat(),
        "summary": analysis.summary,
        "training_recommendation": analysis.training_recommendation,
        "risk_level": analysis.risk_level,
        "model_name": analysis.model_name,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


def _serialize_weekly_analysis(analysis: WeeklyAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "week_start_date": analysis.week_start_date.isoformat(),
        "week_end_date": analysis.week_end_date.isoformat(),
        "status": analysis.status,
        "analysis_version": analysis.analysis_version,
        "summary_short": analysis.summary_short,
        "coach_conclusion": analysis.coach_conclusion,
        "next_week_recommendation": analysis.next_week_recommendation,
        "load_score": analysis.load_score,
        "consistency_score": analysis.consistency_score,
        "fatigue_score": analysis.fatigue_score,
        "balance_score": analysis.balance_score,
        "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
    }


def _serialize_training_plan(plan: TrainingPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "id": plan.id,
        "name": plan.name,
        "status": plan.status,
        "sport_type": plan.sport_type,
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "goal_id": plan.goal_id,
    }


def _serialize_planned_session(session: PlannedSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    return {
        "id": session.id,
        "name": session.name,
        "date": session.training_day.day_date.isoformat() if session.training_day and session.training_day.day_date else None,
        "session_type": session.session_type,
        "sport_type": session.sport_type,
        "expected_duration_min": session.expected_duration_min,
        "expected_distance_km": session.expected_distance_km,
        "target_notes": session.target_notes,
    }


def _get_next_planned_session(db: Session, athlete_id: int, plan: TrainingPlan | None) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= date.today(),
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .limit(1)
    )
    if plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == plan.id)
    return db.scalar(statement)


def _get_latest_activity(db: Session, athlete_id: int) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(GarminActivity.athlete_id == athlete_id)
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )


def _get_latest_daily_health_metric(db: Session, athlete_id: int) -> DailyHealthMetric | None:
    return db.scalar(
        select(DailyHealthMetric)
        .where(DailyHealthMetric.athlete_id == athlete_id)
        .order_by(DailyHealthMetric.metric_date.desc(), DailyHealthMetric.id.desc())
    )


def _get_latest_health_ai_analysis(db: Session, athlete_id: int) -> HealthAiAnalysis | None:
    return db.scalar(
        select(HealthAiAnalysis)
        .where(HealthAiAnalysis.athlete_id == athlete_id)
        .order_by(HealthAiAnalysis.reference_date.desc(), HealthAiAnalysis.created_at.desc(), HealthAiAnalysis.id.desc())
    )


def _get_latest_weekly_analysis(db: Session, athlete_id: int) -> WeeklyAnalysis | None:
    return db.scalar(
        select(WeeklyAnalysis)
        .where(WeeklyAnalysis.athlete_id == athlete_id)
        .order_by(WeeklyAnalysis.week_start_date.desc(), WeeklyAnalysis.id.desc())
    )
