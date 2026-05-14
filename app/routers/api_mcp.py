from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
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
from app.services.health_readiness_service import build_health_readiness_summary, evaluate_health_readiness
from app.services.planning.presentation import describe_session_structure_short, derive_session_metrics
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


@router.get("/compare/planned-vs-done")
def compare_planned_vs_done(
    athlete_id: int = Query(...),
    date_value: str | None = Query(default=None, alias="date"),
    activity_id: int | None = Query(default=None),
    planned_session_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    target_date = _parse_iso_date(date_value, "date") if date_value else None

    activity = _load_activity_for_compare(db, athlete.id, activity_id) if activity_id is not None else None
    planned_session = (
        _load_planned_session_for_compare(db, athlete.id, planned_session_id)
        if planned_session_id is not None else None
    )

    if activity is None and planned_session is None and target_date is not None:
        planned_session = _find_planned_session_by_date(db, athlete.id, target_date)
        activity = _find_activity_by_date(db, athlete.id, target_date)

    if activity is None and planned_session is None and target_date is None:
        activity = _get_latest_activity_for_compare(db, athlete.id)
        if activity is None:
            planned_session = _get_latest_planned_session_for_compare(db, athlete.id)

    match_payload: dict[str, Any] = {
        "source": "none",
        "match_id": None,
        "score": None,
        "confidence": None,
    }

    explicit_match = _resolve_explicit_match(activity, planned_session)
    if explicit_match is not None:
        activity = explicit_match.garmin_activity
        planned_session = explicit_match.planned_session
        match_payload = _serialize_match_payload(explicit_match, source="explicit")
    else:
        if activity is not None and planned_session is None:
            fallback_planned = _find_fallback_planned_for_activity(db, activity)
            if fallback_planned is not None:
                planned_session = fallback_planned
                match_payload = {"source": "date_sport", "match_id": None, "score": None, "confidence": None}
        elif planned_session is not None and activity is None:
            fallback_activity = _find_fallback_activity_for_planned(db, planned_session)
            if fallback_activity is not None:
                activity = fallback_activity
                match_payload = {"source": "date_sport", "match_id": None, "score": None, "confidence": None}
        elif activity is not None and planned_session is not None and _entities_match_by_date_sport(activity, planned_session):
            match_payload = {"source": "date_sport", "match_id": None, "score": None, "confidence": None}

    derived_date = (
        target_date
        or _activity_local_date(activity)
        or _planned_session_date(planned_session)
    )

    session_analysis = _resolve_session_analysis(activity, planned_session)
    analysis_report = _resolve_analysis_report(activity, planned_session)
    differences = _build_differences_payload(planned_session, activity)
    analysis = _build_compare_analysis_payload(
        planned_session=planned_session,
        activity=activity,
        session_analysis=session_analysis,
        analysis_report=analysis_report,
        match_payload=match_payload,
        differences=differences,
    )

    return {
        "athlete": _serialize_athlete_min(athlete),
        "date": derived_date.isoformat() if derived_date is not None else None,
        "planned_session": _serialize_planned_session_compare(planned_session),
        "activity": _serialize_activity_compare(activity),
        "match": match_payload,
        "analysis": analysis,
        "differences": differences,
    }


@router.get("/training/next-session-recommendation")
def get_next_session_recommendation(
    athlete_id: int = Query(...),
    reference_date: str | None = Query(default=None),
    planned_session_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    target_date = _parse_iso_date(reference_date, "reference_date") if reference_date else date.today()
    plan = select_default_training_plan(db, athlete_id=athlete.id, today=target_date)

    target_session = (
        _load_planned_session_for_compare(db, athlete.id, planned_session_id)
        if planned_session_id is not None else None
    )
    if target_session is None:
        target_session = _get_next_session_inclusive(db, athlete.id, plan, target_date)

    last_activity = _get_latest_activity_until(db, athlete.id, target_date)
    latest_metric = _get_latest_daily_health_metric_until(db, athlete.id, target_date)
    latest_ai_analysis = _get_latest_health_ai_analysis_until(db, athlete.id, target_date)
    latest_weekly = _get_latest_weekly_analysis_until(db, athlete.id, target_date)

    health_payload, health_context = _build_health_recommendation_payload(
        db,
        athlete.id,
        target_date,
        latest_metric,
        latest_ai_analysis,
    )
    weekly_payload = _build_weekly_recommendation_payload(latest_weekly)
    data_quality = _build_next_session_data_quality(
        target_session=target_session,
        last_activity=last_activity,
        latest_metric=latest_metric,
        latest_weekly=latest_weekly,
        latest_ai_analysis=latest_ai_analysis,
    )
    recommendation = _build_next_session_recommendation_payload(
        target_session=target_session,
        last_activity=last_activity,
        health_context=health_context,
        weekly_analysis=latest_weekly,
        weekly_payload=weekly_payload,
        data_quality=data_quality,
    )

    return {
        "athlete": _serialize_athlete_min(athlete),
        "reference_date": target_date.isoformat(),
        "plan": _serialize_training_plan_recommendation(plan),
        "next_session": _serialize_next_session_recommendation(target_session),
        "last_activity": _serialize_last_activity_recommendation(last_activity),
        "health": health_payload,
        "weekly": weekly_payload,
        "recommendation": recommendation,
        "data_quality": data_quality,
    }


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


def _get_next_session_inclusive(
    db: Session,
    athlete_id: int,
    plan: TrainingPlan | None,
    target_date: date,
) -> PlannedSession | None:
    primary = _get_next_session_by_range(db, athlete_id, plan, target_date, target_date + date.resolution)
    if primary is not None:
        return primary
    return _get_next_session_by_range(db, athlete_id, plan, target_date, None)


def _get_next_session_by_range(
    db: Session,
    athlete_id: int,
    plan: TrainingPlan | None,
    start_date: date,
    end_date: date | None,
) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(
            selectinload(PlannedSession.training_day),
            selectinload(PlannedSession.planned_session_steps),
        )
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= start_date,
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .limit(1)
    )
    if end_date is not None:
        statement = statement.where(TrainingDay.day_date <= end_date)
    if plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == plan.id)
    return db.scalar(statement)


def _get_latest_activity_until(db: Session, athlete_id: int, reference_date: date) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
            func.date(GarminActivity.start_time) <= reference_date.isoformat(),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )


def _get_latest_daily_health_metric_until(db: Session, athlete_id: int, reference_date: date) -> DailyHealthMetric | None:
    return db.scalar(
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date <= reference_date,
        )
        .order_by(DailyHealthMetric.metric_date.desc(), DailyHealthMetric.id.desc())
    )


def _get_latest_health_ai_analysis_until(db: Session, athlete_id: int, reference_date: date) -> HealthAiAnalysis | None:
    return db.scalar(
        select(HealthAiAnalysis)
        .where(
            HealthAiAnalysis.athlete_id == athlete_id,
            HealthAiAnalysis.reference_date <= reference_date,
        )
        .order_by(HealthAiAnalysis.reference_date.desc(), HealthAiAnalysis.created_at.desc(), HealthAiAnalysis.id.desc())
    )


def _get_latest_weekly_analysis_until(db: Session, athlete_id: int, reference_date: date) -> WeeklyAnalysis | None:
    return db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date <= reference_date,
        )
        .order_by(WeeklyAnalysis.week_start_date.desc(), WeeklyAnalysis.analyzed_at.desc(), WeeklyAnalysis.id.desc())
    )


def _compare_loader_options() -> tuple[Any, ...]:
    return (
        selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session).selectinload(PlannedSession.training_day),
        selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session).selectinload(PlannedSession.planned_session_steps),
        selectinload(GarminActivity.session_analyses),
        selectinload(GarminActivity.analysis_reports),
    )


def _planned_compare_loader_options() -> tuple[Any, ...]:
    return (
        selectinload(PlannedSession.training_day),
        selectinload(PlannedSession.planned_session_steps),
        selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity),
        selectinload(PlannedSession.session_analyses),
        selectinload(PlannedSession.analysis_reports),
    )


def _load_activity_for_compare(db: Session, athlete_id: int, activity_id: int) -> GarminActivity | None:
    activity = db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.id == int(activity_id),
            GarminActivity.athlete_id == athlete_id,
        )
        .options(*_compare_loader_options())
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    return activity


def _load_planned_session_for_compare(db: Session, athlete_id: int, planned_session_id: int) -> PlannedSession | None:
    planned_session = db.scalar(
        select(PlannedSession)
        .where(
            PlannedSession.id == int(planned_session_id),
            PlannedSession.athlete_id == athlete_id,
        )
        .options(*_planned_compare_loader_options())
    )
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    return planned_session


def _find_planned_session_by_date(db: Session, athlete_id: int, target_date: date) -> PlannedSession | None:
    return db.scalar(
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date == target_date,
        )
        .order_by(PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .options(*_planned_compare_loader_options())
    )


def _find_activity_by_date(db: Session, athlete_id: int, target_date: date) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            func.date(GarminActivity.start_time) == target_date.isoformat(),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .options(*_compare_loader_options())
    )


def _get_latest_activity_for_compare(db: Session, athlete_id: int) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(GarminActivity.athlete_id == athlete_id)
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .options(*_compare_loader_options())
    )


def _get_latest_planned_session_for_compare(db: Session, athlete_id: int) -> PlannedSession | None:
    return db.scalar(
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(PlannedSession.athlete_id == athlete_id)
        .order_by(TrainingDay.day_date.desc(), PlannedSession.session_order.desc(), PlannedSession.id.desc())
        .options(*_planned_compare_loader_options())
    )


def _resolve_explicit_match(
    activity: GarminActivity | None,
    planned_session: PlannedSession | None,
) -> ActivitySessionMatch | None:
    if activity is not None and activity.activity_match is not None:
        if planned_session is None or activity.activity_match.planned_session_id_fk == planned_session.id:
            return activity.activity_match
    if planned_session is not None and planned_session.activity_match is not None:
        if activity is None or planned_session.activity_match.garmin_activity_id_fk == activity.id:
            return planned_session.activity_match
    return None


def _find_fallback_planned_for_activity(db: Session, activity: GarminActivity) -> PlannedSession | None:
    activity_date = _activity_local_date(activity)
    if activity_date is None:
        return None
    candidates = list(
        db.scalars(
            select(PlannedSession)
            .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
            .where(
                PlannedSession.athlete_id == activity.athlete_id,
                TrainingDay.day_date == activity_date,
            )
            .order_by(PlannedSession.session_order.asc(), PlannedSession.id.asc())
            .options(*_planned_compare_loader_options())
        ).all()
    )
    return _pick_planned_candidate_for_activity(candidates, activity)


def _find_fallback_activity_for_planned(db: Session, planned_session: PlannedSession) -> GarminActivity | None:
    session_date = _planned_session_date(planned_session)
    if session_date is None:
        return None
    candidates = list(
        db.scalars(
            select(GarminActivity)
            .where(
                GarminActivity.athlete_id == planned_session.athlete_id,
                func.date(GarminActivity.start_time) == session_date.isoformat(),
            )
            .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
            .options(*_compare_loader_options())
        ).all()
    )
    return _pick_activity_candidate_for_planned(candidates, planned_session)


def _pick_planned_candidate_for_activity(
    candidates: list[PlannedSession],
    activity: GarminActivity,
) -> PlannedSession | None:
    if not candidates:
        return None
    exact = [item for item in candidates if _sports_match(item.sport_type, activity.sport_type) and _modalities_match(item.modality, activity.modality)]
    if exact:
        return exact[0]
    sport_only = [item for item in candidates if _sports_match(item.sport_type, activity.sport_type)]
    if sport_only:
        return sport_only[0]
    return None


def _pick_activity_candidate_for_planned(
    candidates: list[GarminActivity],
    planned_session: PlannedSession,
) -> GarminActivity | None:
    if not candidates:
        return None
    exact = [item for item in candidates if _sports_match(item.sport_type, planned_session.sport_type) and _modalities_match(item.modality, planned_session.modality)]
    if exact:
        return exact[0]
    sport_only = [item for item in candidates if _sports_match(item.sport_type, planned_session.sport_type)]
    if sport_only:
        return sport_only[0]
    return None


def _entities_match_by_date_sport(activity: GarminActivity, planned_session: PlannedSession) -> bool:
    activity_date = _activity_local_date(activity)
    planned_date = _planned_session_date(planned_session)
    return (
        activity_date is not None
        and planned_date is not None
        and activity_date == planned_date
        and _sports_match(activity.sport_type, planned_session.sport_type)
        and _modalities_match(activity.modality, planned_session.modality)
    )


def _sports_match(left: str | None, right: str | None) -> bool:
    return _normalize_sport_value(left) == _normalize_sport_value(right) if left and right else False


def _modalities_match(left: str | None, right: str | None) -> bool:
    if left and right:
        return left.strip().lower() == right.strip().lower()
    return True


def _normalize_sport_value(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    aliases = {
        "run": "running",
        "road_cycling": "cycling",
        "bike": "cycling",
        "trail_run": "trail_running",
        "strength_training": "strength",
        "functional_strength_training": "strength",
        "gym": "strength",
        "lap_swimming": "swimming",
        "pool_swim": "swimming",
    }
    return aliases.get(normalized, normalized)


def _activity_local_date(activity: GarminActivity | None) -> date | None:
    if activity is None or activity.start_time is None:
        return None
    return activity.start_time.date()


def _planned_session_date(planned_session: PlannedSession | None) -> date | None:
    if planned_session is None or planned_session.training_day is None:
        return None
    return planned_session.training_day.day_date


def _serialize_match_payload(match: ActivitySessionMatch, *, source: str) -> dict[str, Any]:
    confidence = round(float(match.match_confidence), 3) if match.match_confidence is not None else None
    score = round(float(match.match_confidence) * 100.0, 1) if match.match_confidence is not None else None
    return {
        "source": source,
        "match_id": match.id,
        "score": score,
        "confidence": confidence,
    }


def _serialize_planned_session_compare(session: PlannedSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    metrics = derive_session_metrics(session)
    return {
        "id": session.id,
        "name": session.name,
        "sport": session.sport_type,
        "modality": session.modality,
        "planned_duration_sec": metrics.duration_sec,
        "planned_distance_m": metrics.distance_m,
        "target_type": session.target_type,
        "target_summary": _build_planned_target_summary(session),
        "steps": [_serialize_planned_step(item) for item in session.planned_session_steps],
    }


def _build_planned_target_summary(session: PlannedSession) -> str | None:
    return (
        session.target_notes
        or describe_session_structure_short(session)
        or session.description_text
    )


def _serialize_planned_step(step: Any) -> dict[str, Any]:
    return {
        "id": step.id,
        "step_order": step.step_order,
        "step_type": step.step_type,
        "repeat_count": step.repeat_count,
        "duration_sec": step.duration_sec,
        "distance_m": step.distance_m,
        "target_type": step.target_type,
        "target_hr_zone": step.target_hr_zone,
        "target_hr_min": step.target_hr_min,
        "target_hr_max": step.target_hr_max,
        "target_power_zone": step.target_power_zone,
        "target_power_min": step.target_power_min,
        "target_power_max": step.target_power_max,
        "target_pace_zone": step.target_pace_zone,
        "target_pace_min_sec_km": step.target_pace_min_sec_km,
        "target_pace_max_sec_km": step.target_pace_max_sec_km,
        "target_rpe_zone": step.target_rpe_zone,
        "target_cadence_min": step.target_cadence_min,
        "target_cadence_max": step.target_cadence_max,
        "incline_pct": step.incline_pct,
        "target_notes": step.target_notes,
    }


def _serialize_activity_compare(activity: GarminActivity | None) -> dict[str, Any] | None:
    if activity is None:
        return None
    return {
        "id": activity.id,
        "garmin_activity_id": activity.garmin_activity_id,
        "activity_name": activity.activity_name,
        "sport_type": activity.sport_type,
        "modality": activity.modality,
        "start_time": activity.start_time.isoformat() if activity.start_time else None,
        "duration_sec": activity.duration_sec,
        "distance_m": activity.distance_m,
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "avg_pace_sec_km": activity.avg_pace_sec_km,
        "training_load": activity.training_load,
        "training_effect_aerobic": activity.training_effect_aerobic,
        "training_effect_anaerobic": activity.training_effect_anaerobic,
    }


def _resolve_session_analysis(
    activity: GarminActivity | None,
    planned_session: PlannedSession | None,
) -> SessionAnalysis | None:
    if activity is not None and planned_session is not None:
        matching = [
            item for item in activity.session_analyses
            if item.planned_session_id == planned_session.id
        ]
        if matching:
            return _latest_completed_session_analysis(matching)
    if activity is not None:
        return _latest_completed_session_analysis(activity.session_analyses)
    if planned_session is not None:
        return _latest_completed_session_analysis(planned_session.session_analyses)
    return None


def _resolve_analysis_report(
    activity: GarminActivity | None,
    planned_session: PlannedSession | None,
) -> AnalysisReport | None:
    if activity is not None and planned_session is not None:
        matching = [
            item for item in activity.analysis_reports
            if item.planned_session_id == planned_session.id
        ]
        if matching:
            return _latest_analysis_report(matching)
    if activity is not None and activity.analysis_reports:
        return _latest_analysis_report(activity.analysis_reports)
    if planned_session is not None and planned_session.analysis_reports:
        return _latest_analysis_report(planned_session.analysis_reports)
    return None


def _build_differences_payload(
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
) -> dict[str, Any]:
    planned_duration = None
    planned_distance = None
    if planned_session is not None:
        metrics = derive_session_metrics(planned_session)
        planned_duration = metrics.duration_sec
        planned_distance = metrics.distance_m

    actual_duration = activity.duration_sec if activity is not None else None
    actual_distance = activity.distance_m if activity is not None else None

    return {
        "duration_delta_sec": _safe_delta(actual_duration, planned_duration),
        "distance_delta_m": _safe_delta(actual_distance, planned_distance),
        "duration_ratio": _safe_ratio(actual_duration, planned_duration),
        "distance_ratio": _safe_ratio(actual_distance, planned_distance),
    }


def _safe_delta(actual: float | int | None, planned: float | int | None) -> float | int | None:
    if actual is None or planned is None:
        return None
    delta = float(actual) - float(planned)
    if isinstance(actual, int) and isinstance(planned, int):
        return int(round(delta))
    return round(delta, 1)


def _safe_ratio(actual: float | int | None, planned: float | int | None) -> float | None:
    if actual is None or planned in (None, 0):
        return None
    return round(float(actual) / float(planned), 3)


def _build_compare_analysis_payload(
    *,
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
    session_analysis: SessionAnalysis | None,
    analysis_report: AnalysisReport | None,
    match_payload: dict[str, Any],
    differences: dict[str, Any],
) -> dict[str, Any]:
    warnings = _build_compare_warnings(
        planned_session=planned_session,
        activity=activity,
        session_analysis=session_analysis,
        match_payload=match_payload,
    )
    adherence_score = _resolve_adherence_score(session_analysis, analysis_report)
    summary = _resolve_compare_summary(planned_session, activity, session_analysis, analysis_report)
    recommendation = _resolve_compare_recommendation(planned_session, activity, session_analysis, analysis_report, differences)
    return {
        "session_analysis": _serialize_session_analysis_summary(session_analysis),
        "analysis_report": _serialize_analysis_report_summary(analysis_report),
        "adherence_score": adherence_score,
        "summary": summary,
        "warnings": warnings,
        "recommendation": recommendation,
    }


def _build_compare_warnings(
    *,
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
    session_analysis: SessionAnalysis | None,
    match_payload: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if planned_session is None:
        warnings.append("No hay sesion programada asociada a la actividad consultada.")
    if activity is None:
        warnings.append("No hay actividad realizada asociada a la sesion programada consultada.")
    if planned_session is not None and activity is not None and match_payload.get("source") == "none":
        warnings.append("Se encontraron ambos registros pero sin un vinculo confiable por match explicito ni por fecha/deporte.")
    if session_analysis is None and planned_session is not None and activity is not None:
        warnings.append("No hay analisis comparativo guardado para esta combinacion sesion-actividad.")
    return warnings


def _resolve_adherence_score(
    session_analysis: SessionAnalysis | None,
    analysis_report: AnalysisReport | None,
) -> float | None:
    if session_analysis is not None and session_analysis.compliance_score is not None:
        return round(float(session_analysis.compliance_score), 1)
    if analysis_report is not None and analysis_report.overall_score is not None:
        return round(float(analysis_report.overall_score), 1)
    return None


def _resolve_compare_summary(
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
    session_analysis: SessionAnalysis | None,
    analysis_report: AnalysisReport | None,
) -> str | None:
    for value in (
        session_analysis.summary_short if session_analysis else None,
        session_analysis.coach_conclusion if session_analysis else None,
        analysis_report.summary_text if analysis_report else None,
        analysis_report.final_conclusion_text if analysis_report else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    if planned_session is None and activity is not None:
        return "Hay actividad realizada, pero no se encontro una sesion programada asociada para comparar."
    if activity is None and planned_session is not None:
        return "Hay sesion programada, pero no se encontro una actividad realizada asociada para comparar."
    if planned_session is not None and activity is not None:
        return "Se encontro una sesion programada y una actividad realizada para comparar, sin analisis narrativo guardado."
    return "No se encontraron datos suficientes para construir la comparacion."


def _resolve_compare_recommendation(
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
    session_analysis: SessionAnalysis | None,
    analysis_report: AnalysisReport | None,
    differences: dict[str, Any],
) -> str | None:
    for value in (
        session_analysis.next_recommendation if session_analysis else None,
        analysis_report.recommendation_text if analysis_report else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    if planned_session is None and activity is not None:
        return "Revisar si corresponde vincular manualmente esta actividad a una sesion programada para habilitar mejor feedback."
    if activity is None and planned_session is not None:
        return "Verificar si la actividad todavia no fue sincronizada o si la sesion finalmente no se realizo."
    duration_ratio = differences.get("duration_ratio")
    if isinstance(duration_ratio, float):
        if duration_ratio > 1.2:
            return "La duracion realizada quedo por encima de lo planificado; conviene revisar impacto de carga y recuperacion."
        if duration_ratio < 0.8:
            return "La duracion realizada quedo por debajo de lo planificado; conviene revisar si hubo recorte por fatiga, tiempo o terreno."
    return None


def _serialize_training_plan_recommendation(plan: TrainingPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "id": plan.id,
        "name": plan.name,
        "status": plan.status,
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
    }


def _serialize_next_session_recommendation(session: PlannedSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    metrics = derive_session_metrics(session)
    return {
        "id": session.id,
        "date": session.training_day.day_date.isoformat() if session.training_day and session.training_day.day_date else None,
        "name": session.name,
        "sport": session.sport_type,
        "modality": session.modality,
        "planned_duration_sec": metrics.duration_sec,
        "planned_distance_m": metrics.distance_m,
        "target_summary": _build_planned_target_summary(session),
    }


def _serialize_last_activity_recommendation(activity: GarminActivity | None) -> dict[str, Any] | None:
    if activity is None:
        return None
    return {
        "id": activity.id,
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


def _build_health_recommendation_payload(
    db: Session,
    athlete_id: int,
    reference_date: date,
    latest_metric: DailyHealthMetric | None,
    latest_ai_analysis: HealthAiAnalysis | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if latest_metric is None:
        return None, {
            "readiness_score": None,
            "readiness_label": None,
            "main_limiter": None,
            "risk_level": latest_ai_analysis.risk_level if latest_ai_analysis is not None else None,
            "has_health": False,
            "confidence": "low",
        }

    summary = build_health_readiness_summary(db, athlete_id, latest_metric.metric_date)
    evaluation = evaluate_health_readiness(summary)
    payload = {
        "date": latest_metric.metric_date.isoformat(),
        "readiness_score": evaluation.readiness_score,
        "readiness_label": evaluation.readiness_label,
        "sleep_duration_minutes": latest_metric.sleep_duration_minutes,
        "body_battery_morning": latest_metric.body_battery_morning,
        "hrv_value": latest_metric.hrv_value or latest_metric.hrv_avg_ms,
        "resting_hr": latest_metric.resting_hr,
        "main_limiter": evaluation.main_limiter,
    }
    return payload, {
        "readiness_score": evaluation.readiness_score,
        "readiness_label": evaluation.readiness_label,
        "main_limiter": evaluation.main_limiter,
        "risk_level": latest_ai_analysis.risk_level if latest_ai_analysis is not None else None,
        "has_health": True,
        "confidence": "low" if evaluation.data_quality == "poor" else "medium" if evaluation.data_quality == "fair" else "high",
        "reference_date": latest_metric.metric_date.isoformat(),
    }


def _build_weekly_recommendation_payload(analysis: WeeklyAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "week_start_date": analysis.week_start_date.isoformat(),
        "summary": analysis.summary_short or analysis.coach_conclusion,
        "risk_level": _weekly_risk_level(analysis),
        "load_summary": _weekly_load_summary_text(analysis),
    }


def _weekly_risk_level(analysis: WeeklyAnalysis) -> str:
    fatigue = float(analysis.fatigue_score or 0)
    load = float(analysis.load_score or 0)
    if fatigue >= 80 or load >= 85:
        return "high"
    if fatigue >= 60 or load >= 65:
        return "moderate"
    return "low"


def _weekly_load_summary_text(analysis: WeeklyAnalysis) -> str | None:
    parts: list[str] = []
    if analysis.total_sessions is not None:
        parts.append(f"{analysis.total_sessions} sesiones")
    if analysis.total_duration_sec is not None:
        parts.append(f"{int(round(analysis.total_duration_sec / 60.0))} min")
    if analysis.total_distance_m is not None:
        parts.append(f"{round(float(analysis.total_distance_m) / 1000.0, 1)} km")
    return ", ".join(parts) if parts else None


def _build_next_session_data_quality(
    *,
    target_session: PlannedSession | None,
    last_activity: GarminActivity | None,
    latest_metric: DailyHealthMetric | None,
    latest_weekly: WeeklyAnalysis | None,
    latest_ai_analysis: HealthAiAnalysis | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    if target_session is None:
        warnings.append("No hay proxima sesion planificada disponible para analizar.")
    if last_activity is None:
        warnings.append("No hay actividad reciente registrada hasta la fecha de referencia.")
    if latest_metric is None:
        warnings.append("No hay metricas de salud disponibles hasta la fecha de referencia.")
    if latest_weekly is None:
        warnings.append("No hay analisis semanal disponible.")
    if latest_ai_analysis is None:
        warnings.append("No hay analisis AI de salud disponible; la recomendacion usa reglas locales.")
    return {
        "has_next_session": target_session is not None,
        "has_last_activity": last_activity is not None,
        "has_health": latest_metric is not None,
        "has_weekly_analysis": latest_weekly is not None,
        "warnings": warnings,
    }


def _build_next_session_recommendation_payload(
    *,
    target_session: PlannedSession | None,
    last_activity: GarminActivity | None,
    health_context: dict[str, Any],
    weekly_analysis: WeeklyAnalysis | None,
    weekly_payload: dict[str, Any] | None,
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    if target_session is None:
        return {
            "decision": "no_data",
            "title": "Sin proxima sesion planificada",
            "summary": "No hay una sesion objetivo para evaluar desde la fecha de referencia.",
            "reasons": ["No se encontro proxima sesion planificada."],
            "suggested_adjustment": "Revisar el plan y definir la siguiente sesion antes de ajustar la carga.",
            "risk_flags": [],
            "confidence": "low",
        }

    reasons: list[str] = []
    risk_flags: list[str] = []
    decision = "keep"
    title = "Mantener la proxima sesion"
    summary = "El contexto actual permite sostener la sesion prevista."
    suggested_adjustment = "Mantener la sesion segun lo planificado."

    readiness_score = health_context.get("readiness_score")
    readiness_label = health_context.get("readiness_label")
    risk_level = (health_context.get("risk_level") or (weekly_payload or {}).get("risk_level") or "").lower()
    is_intense = _is_intense_planned_session(target_session)

    if readiness_score is not None:
        reasons.append(f"Readiness actual: {readiness_score} ({readiness_label}).")
    if health_context.get("main_limiter"):
        risk_flags.append(f"main_limiter:{health_context['main_limiter']}")
    if risk_level in {"high", "moderate"}:
        risk_flags.append(f"risk_level:{risk_level}")

    if readiness_score is not None and readiness_score < 50:
        decision = "rest"
        title = "Priorizar descanso o recuperacion"
        summary = "El estado actual no acompana una sesion exigente."
        suggested_adjustment = "Cambiar la sesion por descanso, movilidad o recuperacion muy suave."
        reasons.append("El readiness aparece en zona roja.")
    elif readiness_score is not None and readiness_score < 65:
        decision = "replace_easy"
        title = "Conviene pasar a una sesion facil"
        summary = "El estado actual sugiere evitar una carga exigente."
        suggested_adjustment = "Reemplazar por rodaje suave, tecnica o trabajo regenerativo."
        reasons.append("El readiness aparece limitado para sostener intensidad.")
    elif risk_level == "high":
        decision = "caution"
        title = "Entrenar con cautela"
        summary = "Hay senales de riesgo elevadas en el contexto reciente."
        suggested_adjustment = "Si se hace la sesion, bajar volumen o intensidad y monitorear sensaciones."
        reasons.append("El riesgo reciente figura como alto.")

    if last_activity is not None and is_intense:
        if (last_activity.training_load or 0) >= 150:
            if decision == "keep":
                decision = "reduce"
                title = "Reducir la carga de la proxima sesion"
                summary = "La carga reciente fue alta para encadenar otra sesion intensa sin ajuste."
                suggested_adjustment = "Recortar volumen, bloques de calidad o tiempo total."
            reasons.append("La ultima actividad tuvo training load alto.")
            risk_flags.append("high_recent_training_load")
        if (last_activity.training_effect_aerobic or 0) >= 4.0:
            if decision in {"keep", "caution"}:
                decision = "reduce"
                title = "Conviene moderar la sesion"
                summary = "La ultima actividad dejo una carga aerobica significativa."
                suggested_adjustment = "Bajar la intensidad o convertir parte de la sesion en trabajo controlado."
            reasons.append("La ultima actividad tuvo training effect aerobico alto.")
            risk_flags.append("high_recent_aerobic_te")

    if weekly_analysis is not None and _weekly_risk_level(weekly_analysis) == "high" and decision == "keep":
        decision = "caution"
        title = "Sostener con cautela"
        summary = "La semana viene cargada aunque no hay una alerta aguda clara hoy."
        suggested_adjustment = "Mantener solo si las sensaciones son buenas; si no, bajar un escalon."
        reasons.append("El analisis semanal muestra carga o fatiga altas.")

    if not reasons:
        reasons.append("No aparecen alertas fuertes en los datos disponibles.")

    confidence = _recommendation_confidence(data_quality, health_context)

    return {
        "decision": decision,
        "title": title,
        "summary": summary,
        "reasons": reasons,
        "suggested_adjustment": suggested_adjustment,
        "risk_flags": risk_flags,
        "confidence": confidence,
    }


def _is_intense_planned_session(session: PlannedSession) -> bool:
    text = " ".join(
        str(item).lower()
        for item in (
            session.session_type,
            session.target_notes,
            session.description_text,
            session.name,
            session.target_hr_zone,
            session.target_pace_zone,
            session.target_power_zone,
            session.target_rpe_zone,
        )
        if item
    )
    return bool(session.is_key_session) or any(
        token in text
        for token in ("z4", "z5", "interval", "series", "tempo", "threshold", "umbral", "vo2", "intenso", "hard")
    )


def _recommendation_confidence(data_quality: dict[str, Any], health_context: dict[str, Any]) -> str:
    if not data_quality.get("has_next_session"):
        return "low"
    if not data_quality.get("has_health"):
        return "low"
    if health_context.get("confidence") == "low":
        return "low"
    if not data_quality.get("has_last_activity") or not data_quality.get("has_weekly_analysis"):
        return "medium"
    return "high"
