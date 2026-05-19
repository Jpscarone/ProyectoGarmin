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
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.db.session import get_db
from app.services.analysis_v2.weekly_analysis_service import build_week_context, compute_week_metrics
from app.services.health_readiness_service import build_health_readiness_summary, evaluate_health_readiness
from app.services.planning.presentation import describe_session_structure_short, derive_session_metrics
from app.services.athlete_context import get_current_athlete, get_current_training_plan
from app.services.mcp_context_service import (
    build_last_activity_feedback_payload,
    build_next_session_context_payload,
    build_session_feedback_payload,
    build_week_context_payload,
)
from app.services.athlete_access_code_service import resolve_athlete_by_access_code
from app.services.mcp_security import verify_mcp_bearer_token
from app.services.training_plan_service import select_default_training_plan
from app.services.session_completion_service import completed_duration_sec, is_manually_completed_strength_session, is_session_completed
from app.utils.datetime_utils import today_local
from app.routers.planned_sessions import _build_technical_view, _get_preferred_session_analysis


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


@router.get("/me/identify")
def identify_mcp_athlete(
    request: Request,
    access_code: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return {"athlete": _serialize_athlete_min(athlete)}


@router.get("/me/activities/recent")
def list_my_recent_activities(
    request: Request,
    access_code: str = Query(...),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return list_recent_activities(athlete_id=athlete.id, limit=limit, db=db)


@router.get("/me/health/summary")
def read_my_health_summary(
    request: Request,
    access_code: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return read_health_summary(athlete_id=athlete.id, db=db)


@router.get("/me/training/status")
def read_my_training_status(
    request: Request,
    access_code: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return read_training_status(athlete_id=athlete.id, db=db)


@router.get("/me/day-overview")
def get_my_day_overview(
    request: Request,
    access_code: str = Query(...),
    date_value: str = Query(..., alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return get_day_overview(athlete_id=athlete.id, date_value=date_value, db=db)


@router.get("/me/compare/planned-vs-done")
def compare_my_planned_vs_done(
    request: Request,
    access_code: str = Query(...),
    date_value: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return compare_planned_vs_done(
        athlete_id=athlete.id,
        date_value=date_value,
        db=db,
    )


@router.get("/me/training/next-session-recommendation")
def get_my_next_session_recommendation(
    request: Request,
    access_code: str = Query(...),
    reference_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return get_next_session_recommendation(
        athlete_id=athlete.id,
        reference_date=reference_date,
        db=db,
    )


@router.get("/me/training/week-load-summary")
def get_my_week_load_summary(
    request: Request,
    access_code: str = Query(...),
    week_start_date: str | None = Query(default=None),
    compare_previous: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return get_week_load_summary(
        athlete_id=athlete.id,
        week_start_date=week_start_date,
        compare_previous=compare_previous,
        db=db,
    )


@router.get("/me/analysis/session-payload")
def get_my_session_analysis_payload(
    request: Request,
    access_code: str = Query(...),
    planned_session_id: int | None = Query(default=None),
    activity_id: int | None = Query(default=None),
    date_value: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _reject_forbidden_query_params(request, "athlete_id")
    athlete = resolve_athlete_by_access_code(access_code, db)
    return get_session_analysis_payload(
        athlete_id=athlete.id,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        date_value=date_value,
        db=db,
    )


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
    reference_date = today_local(athlete=athlete)
    plan = select_default_training_plan(db, athlete_id=athlete.id, today=reference_date)
    next_session = _get_next_planned_session(db, athlete.id, plan, reference_date)
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


@router.get("/training/day-overview")
def get_day_overview(
    athlete_id: int = Query(...),
    date_value: str = Query(..., alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    target_date = _parse_mcp_date(date_value, "date")
    training_days = _get_training_days_for_date(db, athlete.id, target_date)
    planned_sessions = _get_planned_sessions_for_date(db, athlete.id, target_date)
    activities = _get_activities_for_exact_date(db, athlete.id, target_date)
    matches = _build_day_matches_payload(db, planned_sessions, activities)
    manual_sessions = _serialize_day_manual_sessions(planned_sessions)
    warnings: list[str] = []
    if len(training_days) > 1:
        warnings.append("Hay mas de un training_day para la misma fecha; se muestra el primero y se incluyen todas las sesiones.")
    summary = _build_day_overview_summary(planned_sessions, activities, matches, manual_sessions)
    if not planned_sessions:
        warnings.append("No hay sesiones planificadas para esta fecha.")
    if not activities:
        warnings.append("No hay actividades Garmin registradas para esta fecha.")
    return {
        "athlete": _serialize_athlete_min(athlete),
        "date": target_date.isoformat(),
        "training_day": _serialize_training_day_overview(training_days[0] if training_days else None),
        "planned_sessions": [_serialize_day_planned_session(item, matches) for item in planned_sessions],
        "activities": [_serialize_activity_recent(item) for item in activities],
        "manual_sessions": manual_sessions,
        "matches": matches,
        "summary": summary,
        "data_quality": {"warnings": warnings},
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
    target_date = _parse_iso_date(reference_date, "reference_date") if reference_date else today_local(athlete=athlete)
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


@router.get("/training/week-load-summary")
def get_week_load_summary(
    athlete_id: int = Query(...),
    week_start_date: str | None = Query(default=None),
    compare_previous: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    selected_start = (
        _parse_iso_date(week_start_date, "week_start_date")
        if week_start_date else _week_start_from_date(today_local(athlete=athlete))
    )
    week_end = _week_end_from_start(selected_start)

    context = build_week_context(db, athlete.id, selected_start)
    metrics = compute_week_metrics(context)
    weekly_analysis = _get_weekly_analysis_for_start(db, athlete.id, selected_start)

    previous_payload = None
    previous_summary = None
    if compare_previous:
        previous_start = selected_start - 7 * date.resolution
        previous_context = build_week_context(db, athlete.id, previous_start)
        previous_metrics = compute_week_metrics(previous_context)
        previous_summary = _build_previous_week_summary_payload(selected_start, previous_context, previous_metrics)
        previous_payload = previous_summary

    health_payload = _build_week_load_health_payload(db, athlete.id, selected_start, week_end)
    sports_breakdown = _sports_breakdown(
        list(getattr(context, "activities", []) or []),
        list(getattr(context, "planned_sessions", []) or []),
    )
    manual_sessions = _serialize_manual_week_sessions(context)
    week_payload = _build_week_load_week_payload(
        context,
        metrics,
        sports_breakdown=sports_breakdown,
        manual_sessions=manual_sessions,
    )
    intensity_payload = _build_week_load_intensity_payload(context, metrics)
    weekly_analysis_payload = _build_week_load_weekly_analysis_payload(weekly_analysis)
    data_quality = _build_week_load_data_quality(context, weekly_analysis, health_payload)
    recommendation = _build_week_load_recommendation(
        week_payload=week_payload,
        intensity_payload=intensity_payload,
        health_payload=health_payload,
        weekly_analysis=weekly_analysis,
        previous_summary=previous_summary,
        data_quality=data_quality,
    )

    return {
        "athlete": _serialize_athlete_min(athlete),
        "week": week_payload,
        "sports_breakdown": sports_breakdown,
        "manual_sessions": manual_sessions,
        "intensity": intensity_payload,
        "health": health_payload,
        "weekly_analysis": weekly_analysis_payload,
        "previous_week": previous_payload,
        "recommendation": recommendation,
        "data_quality": data_quality,
    }


@router.get("/analysis/session-payload")
def get_session_analysis_payload(
    athlete_id: int = Query(...),
    planned_session_id: int | None = Query(default=None),
    activity_id: int | None = Query(default=None),
    date_value: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    athlete = _get_athlete_or_404(db, athlete_id)
    resolved_by = "latest_activity"
    target_date = _parse_iso_date(date_value, "date") if date_value else None

    planned_session = None
    activity = None
    if planned_session_id is not None:
        resolved_by = "planned_session_id"
        planned_session = _load_planned_session_analysis_payload(db, athlete.id, planned_session_id)
        activity = (
            planned_session.activity_match.garmin_activity
            if planned_session.activity_match and planned_session.activity_match.garmin_activity is not None
            else _find_fallback_activity_for_planned(db, planned_session)
        )
    elif activity_id is not None:
        resolved_by = "activity_id"
        activity = _load_activity_analysis_payload(db, athlete.id, activity_id)
        planned_session = (
            activity.activity_match.planned_session
            if activity.activity_match and activity.activity_match.planned_session is not None
            else _find_fallback_planned_for_activity(db, activity)
        )
    elif target_date is not None:
        resolved_by = "date"
        planned_session = _find_planned_session_by_date(db, athlete.id, target_date)
        activity = _find_activity_by_date_analysis_payload(db, athlete.id, target_date)
        if planned_session is None and activity is not None:
            planned_session = _find_fallback_planned_for_activity(db, activity)
        if activity is None and planned_session is not None:
            activity = _find_fallback_activity_for_planned(db, planned_session)
    else:
        activity = _get_latest_activity_analysis_payload(db, athlete.id)
        if activity is not None:
            planned_session = (
                activity.activity_match.planned_session
                if activity.activity_match and activity.activity_match.planned_session is not None
                else _find_fallback_planned_for_activity(db, activity)
            )
        else:
            planned_session = _get_latest_planned_session_for_compare(db, athlete.id)

    analysis = _resolve_session_payload_analysis(db, planned_session, activity)
    metrics_payload = analysis.metrics_json if analysis and isinstance(analysis.metrics_json, dict) else {}
    context_payload = metrics_payload.get("context", {}) if isinstance(metrics_payload, dict) else {}
    technical_view = _build_technical_view(metrics_payload, context_payload, analysis)
    analysis_report = _resolve_analysis_report(activity, planned_session)

    data_quality = _build_session_payload_data_quality(
        planned_session=planned_session,
        activity=activity,
        analysis=analysis,
        technical_view=technical_view,
    )

    return {
        "athlete": _serialize_athlete_min(athlete),
        "resolved_by": resolved_by,
        "planned_session": _serialize_analysis_payload_planned_session(planned_session),
        "planned_steps": _serialize_analysis_payload_planned_steps(planned_session),
        "activity": _serialize_analysis_payload_activity(activity),
        "laps": _serialize_analysis_payload_laps(activity),
        "step_vs_lap_comparison": _serialize_step_vs_lap_comparison(technical_view),
        "metrics_json": technical_view.get("metrics_json") or {},
        "llm_json": technical_view.get("llm_json") or {},
        "saved_analysis": {
            "session_analysis": _serialize_session_analysis_summary(analysis),
            "analysis_report": _serialize_analysis_report_summary(analysis_report),
        },
        "data_quality": data_quality,
    }


def _parse_iso_date(raw_value: str, field_name: str) -> date:
    return _parse_mcp_date(raw_value, field_name)


def _parse_mcp_date(raw_value: str, field_name: str) -> date:
    normalized = (raw_value or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} es obligatorio.",
        )
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        try:
            day_text, month_text, year_text = normalized.split("-", 2)
            return date(int(year_text), int(month_text), int(day_text))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{field_name} debe tener formato YYYY-MM-DD o DD-MM-YYYY.",
            ) from exc


def _reject_forbidden_query_params(request: Request, *names: str) -> None:
    for name in names:
        if name in request.query_params:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{name} no esta permitido en este endpoint.",
            )


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


def _get_next_planned_session(
    db: Session,
    athlete_id: int,
    plan: TrainingPlan | None,
    reference_date: date,
) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= reference_date,
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


def _get_weekly_analysis_for_start(db: Session, athlete_id: int, week_start_date: date) -> WeeklyAnalysis | None:
    return db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start_date,
        )
        .order_by(WeeklyAnalysis.analyzed_at.desc(), WeeklyAnalysis.id.desc())
    )


def _analysis_payload_loader_options() -> tuple[Any, ...]:
    return (
        selectinload(GarminActivity.laps),
        selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session).selectinload(PlannedSession.training_day),
        selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session).selectinload(PlannedSession.planned_session_steps),
        selectinload(GarminActivity.session_analyses),
        selectinload(GarminActivity.analysis_reports),
    )


def _planned_analysis_payload_loader_options() -> tuple[Any, ...]:
    return (
        selectinload(PlannedSession.training_day),
        selectinload(PlannedSession.planned_session_steps),
        selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity).selectinload(GarminActivity.laps),
        selectinload(PlannedSession.session_analyses),
        selectinload(PlannedSession.analysis_reports),
    )


def _load_activity_analysis_payload(db: Session, athlete_id: int, activity_id: int) -> GarminActivity | None:
    activity = db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.id == int(activity_id),
            GarminActivity.athlete_id == athlete_id,
        )
        .options(*_analysis_payload_loader_options())
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    return activity


def _load_planned_session_analysis_payload(db: Session, athlete_id: int, planned_session_id: int) -> PlannedSession | None:
    session = db.scalar(
        select(PlannedSession)
        .where(
            PlannedSession.id == int(planned_session_id),
            PlannedSession.athlete_id == athlete_id,
        )
        .options(*_planned_analysis_payload_loader_options())
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    return session


def _find_activity_by_date_analysis_payload(db: Session, athlete_id: int, target_date: date) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            func.date(GarminActivity.start_time) == target_date.isoformat(),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .options(*_analysis_payload_loader_options())
    )


def _get_latest_activity_analysis_payload(db: Session, athlete_id: int) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(GarminActivity.athlete_id == athlete_id)
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .options(*_analysis_payload_loader_options())
    )


def _training_day_loader_options() -> tuple[Any, ...]:
    return (
        selectinload(TrainingDay.training_plan),
        selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity),
        selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.planned_session_steps),
    )


def _get_training_days_for_date(db: Session, athlete_id: int, target_date: date) -> list[TrainingDay]:
    return list(
        db.scalars(
            select(TrainingDay)
            .where(
                TrainingDay.athlete_id == athlete_id,
                TrainingDay.day_date == target_date,
            )
            .order_by(TrainingDay.id.asc())
            .options(*_training_day_loader_options())
        ).all()
    )


def _get_planned_sessions_for_date(db: Session, athlete_id: int, target_date: date) -> list[PlannedSession]:
    return list(
        db.scalars(
            select(PlannedSession)
            .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
            .where(
                PlannedSession.athlete_id == athlete_id,
                TrainingDay.day_date == target_date,
            )
            .order_by(PlannedSession.session_order.asc(), PlannedSession.id.asc())
            .options(*_planned_compare_loader_options())
        ).all()
    )


def _get_activities_for_exact_date(db: Session, athlete_id: int, target_date: date) -> list[GarminActivity]:
    candidates = list(
        db.scalars(
            select(GarminActivity)
            .where(
                GarminActivity.athlete_id == athlete_id,
                func.date(GarminActivity.start_time) == target_date.isoformat(),
            )
            .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
            .options(*_compare_loader_options())
        ).all()
    )
    return [item for item in candidates if _activity_local_date(item) == target_date]


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
        "gimnasio": "strength",
        "fuerza": "strength",
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


def _serialize_training_day_overview(training_day: TrainingDay | None) -> dict[str, Any] | None:
    if training_day is None:
        return None
    return {
        "id": training_day.id,
        "date": training_day.day_date.isoformat() if training_day.day_date else None,
        "day_type": training_day.day_type,
        "notes": training_day.day_notes,
    }


def _serialize_day_planned_session(session: PlannedSession, matches: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = derive_session_metrics(session)
    return {
        "id": session.id,
        "name": session.name,
        "sport": session.sport_type,
        "modality": session.modality,
        "planned_duration_sec": metrics.duration_sec,
        "planned_distance_m": metrics.distance_m,
        "status": _planned_session_day_status(session, matches),
        "target_summary": _build_planned_target_summary(session),
        "notes": session.target_notes or session.description_text,
    }


def _planned_session_day_status(session: PlannedSession, matches: list[dict[str, Any]]) -> str:
    linked_match = next((item for item in matches if item.get("planned_session_id") == session.id and item.get("activity_id") is not None), None)
    if linked_match is not None:
        return "completed"
    if is_session_completed(session) or is_manually_completed_strength_session(session):
        return "completed"
    return "no_activity"


def _serialize_day_manual_sessions(planned_sessions: list[PlannedSession]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for session in planned_sessions:
        if not is_manually_completed_strength_session(session):
            continue
        payload.append(
            {
                "id": session.id,
                "date": session.training_day.day_date.isoformat() if session.training_day and session.training_day.day_date else None,
                "name": session.name,
                "sport": _normalize_sport_value(session.sport_type) or session.sport_type,
                "modality": session.modality,
                "duration_sec": completed_duration_sec(session),
                "status": "completed",
                "source": "planned_session_manual",
            }
        )
    return payload


def _build_day_matches_payload(
    db: Session,
    planned_sessions: list[PlannedSession],
    activities: list[GarminActivity],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    added_pairs: set[tuple[int | None, int | None]] = set()

    for planned_session in planned_sessions:
        explicit = _resolve_explicit_match(planned_session.activity_match.garmin_activity if planned_session.activity_match else None, planned_session)
        if explicit is not None:
            pair = (explicit.planned_session_id_fk, explicit.garmin_activity_id_fk)
            if pair not in added_pairs:
                payload = _serialize_match_payload(explicit, source="explicit")
                matches.append(
                    {
                        "planned_session_id": explicit.planned_session_id_fk,
                        "activity_id": explicit.garmin_activity_id_fk,
                        "source": payload["source"],
                        "score": payload["score"],
                    }
                )
                added_pairs.add(pair)
            continue

        fallback_activity = _pick_activity_candidate_for_planned(activities, planned_session)
        if fallback_activity is not None:
            pair = (planned_session.id, fallback_activity.id)
            if pair not in added_pairs:
                matches.append(
                    {
                        "planned_session_id": planned_session.id,
                        "activity_id": fallback_activity.id,
                        "source": "date_sport",
                        "score": None,
                    }
                )
                added_pairs.add(pair)

    for activity in activities:
        explicit = _resolve_explicit_match(activity, activity.activity_match.planned_session if activity.activity_match else None)
        if explicit is not None:
            continue
        if not any(item.get("activity_id") == activity.id for item in matches):
            fallback_planned = _pick_planned_candidate_for_activity(planned_sessions, activity)
            if fallback_planned is not None:
                pair = (fallback_planned.id, activity.id)
                if pair not in added_pairs:
                    matches.append(
                        {
                            "planned_session_id": fallback_planned.id,
                            "activity_id": activity.id,
                            "source": "date_sport",
                            "score": None,
                        }
                    )
                    added_pairs.add(pair)

    return matches


def _build_day_overview_summary(
    planned_sessions: list[PlannedSession],
    activities: list[GarminActivity],
    matches: list[dict[str, Any]],
    manual_sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    has_planned = bool(planned_sessions)
    has_completed_training = bool(activities or manual_sessions)
    has_garmin_activities = bool(activities)
    if has_planned and manual_sessions and not has_garmin_activities:
        message = (
            "Hay una sesión programada marcada como realizada manualmente y no hay actividad Garmin asociada."
            if len(manual_sessions) == 1
            else "Hay sesiones programadas marcadas como realizadas manualmente y no hay actividades Garmin asociadas."
        )
    elif has_planned and not has_completed_training:
        message = "Hay una sesión programada pero no hay actividad Garmin realizada asociada." if len(planned_sessions) == 1 else "Hay sesiones programadas pero no hay actividad Garmin realizada asociada."
    elif not has_planned and has_completed_training:
        message = "Hay actividad Garmin realizada pero no hay planificación asociada para esa fecha."
    elif has_planned and has_completed_training:
        explicit_count = sum(1 for item in matches if item.get("source") == "explicit")
        if explicit_count:
            message = "Hay sesiones planificadas y actividades realizadas con coincidencias asociadas."
        elif manual_sessions and not has_garmin_activities:
            message = "Hay sesiones planificadas realizadas manualmente para esa fecha."
        else:
            message = "Hay sesiones planificadas y actividades realizadas en la fecha, pero sin una vinculación explícita guardada."
    else:
        message = "No hay sesiones planificadas ni actividades Garmin registradas para esa fecha."
    return {
        "has_planned_sessions": has_planned,
        "has_completed_activities": has_completed_training,
        "message": message,
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


def _week_start_from_date(value: date) -> date:
    return value - ((value.weekday()) * date.resolution)


def _week_end_from_start(value: date) -> date:
    return value + (6 * date.resolution)


def _build_week_load_week_payload(
    context: Any,
    metrics: dict[str, Any],
    *,
    sports_breakdown: dict[str, Any] | None = None,
    manual_sessions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    totals = metrics.get("totals", {})
    compliance = metrics.get("compliance", {})
    activities = list(getattr(context, "activities", []) or [])
    manual_sessions = manual_sessions if manual_sessions is not None else _serialize_manual_week_sessions(context)
    sports_breakdown = sports_breakdown if sports_breakdown is not None else _sports_breakdown(
        activities,
        list(getattr(context, "planned_sessions", []) or []),
    )
    garmin_activities_count = len(activities)
    completed_manual_sessions_count = len(manual_sessions)
    completed_strength_sessions_count = _count_completed_strength_sessions(
        activities,
        list(getattr(context, "planned_sessions", []) or []),
    )
    total_completed_training_count = garmin_activities_count + completed_manual_sessions_count
    weighted_hr = _weighted_average_hr(activities)
    return {
        "start_date": context.week_start_date.isoformat(),
        "end_date": context.week_end_date.isoformat(),
        "completed_activities_count": total_completed_training_count,
        "garmin_activities_count": garmin_activities_count,
        "completed_manual_sessions_count": completed_manual_sessions_count,
        "completed_strength_sessions_count": completed_strength_sessions_count,
        "total_completed_training_count": total_completed_training_count,
        "planned_sessions_count": compliance.get("planned_sessions") or 0,
        "completed_sessions_count": compliance.get("completed_sessions") or 0,
        "total_duration_sec": totals.get("total_duration_sec") or 0,
        "total_distance_m": totals.get("total_distance_m") or 0,
        "total_training_load": _total_training_load(activities),
        "avg_hr_weighted": weighted_hr,
        "sports_breakdown": sports_breakdown,
    }


def _weighted_average_hr(activities: list[Any]) -> float | None:
    weighted_sum = 0.0
    total_duration = 0.0
    for activity in activities:
        avg_hr = getattr(activity, "avg_hr", None)
        duration = getattr(activity, "duration_sec", None)
        if avg_hr is None or duration in (None, 0):
            continue
        weighted_sum += float(avg_hr) * float(duration)
        total_duration += float(duration)
    if total_duration <= 0:
        return None
    return round(weighted_sum / total_duration, 1)


def _total_training_load(activities: list[Any]) -> float:
    total = sum(float(getattr(activity, "training_load", 0) or 0) for activity in activities)
    return round(total, 1)


def _sports_breakdown(activities: list[Any], planned_sessions: list[Any]) -> dict[str, Any]:
    buckets: dict[str, dict[str, float | int]] = {
        "running": {"planned_count": 0, "completed_count": 0, "manual_completed_count": 0, "activities_count": 0, "total_duration_sec": 0, "total_distance_m": 0.0, "total_training_load": 0.0},
        "cycling": {"planned_count": 0, "completed_count": 0, "manual_completed_count": 0, "activities_count": 0, "total_duration_sec": 0, "total_distance_m": 0.0, "total_training_load": 0.0},
        "strength": {"planned_count": 0, "completed_count": 0, "manual_completed_count": 0, "activities_count": 0, "total_duration_sec": 0, "total_distance_m": 0.0, "total_training_load": 0.0},
        "other": {"planned_count": 0, "completed_count": 0, "manual_completed_count": 0, "activities_count": 0, "total_duration_sec": 0, "total_distance_m": 0.0, "total_training_load": 0.0},
    }
    for session in planned_sessions:
        bucket = _sport_bucket(getattr(session, "sport_type", None))
        current = buckets[bucket]
        current["planned_count"] += 1
    for activity in activities:
        bucket = _sport_bucket(getattr(activity, "sport_type", None))
        current = buckets[bucket]
        current["activities_count"] += 1
        current["completed_count"] += 1
        current["total_duration_sec"] += int(getattr(activity, "duration_sec", 0) or 0)
        current["total_distance_m"] += float(getattr(activity, "distance_m", 0) or 0)
        current["total_training_load"] += float(getattr(activity, "training_load", 0) or 0)
    for session in planned_sessions:
        if not getattr(session, "manual_completed", False):
            continue
        if getattr(session, "matched", False) or getattr(session, "linked_activity_id", None) is not None:
            continue
        bucket = _sport_bucket(getattr(session, "sport_type", None))
        current = buckets[bucket]
        current["manual_completed_count"] += 1
        current["completed_count"] += 1
        current["total_duration_sec"] += int(getattr(session, "completed_duration_sec", 0) or 0)
    for item in buckets.values():
        item["total_distance_m"] = round(float(item["total_distance_m"]), 1)
        item["total_training_load"] = round(float(item["total_training_load"]), 1)
    return buckets


def _serialize_manual_week_sessions(context: Any) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for session in list(getattr(context, "planned_sessions", []) or []):
        if not getattr(session, "manual_completed", False):
            continue
        if getattr(session, "matched", False) or getattr(session, "linked_activity_id", None) is not None:
            continue
        payload.append(
            {
                "id": getattr(session, "planned_session_id", None),
                "date": session.session_date.isoformat() if getattr(session, "session_date", None) else None,
                "name": getattr(session, "title", None),
                "sport": _normalize_sport_value(getattr(session, "sport_type", None)) or getattr(session, "sport_type", None),
                "modality": getattr(session, "modality", None),
                "duration_sec": int(getattr(session, "completed_duration_sec", 0) or 0),
                "status": "completed",
                "source": "planned_session_manual",
            }
        )
    return payload


def _count_completed_strength_sessions(activities: list[Any], planned_sessions: list[Any]) -> int:
    count = sum(1 for activity in activities if _sport_bucket(getattr(activity, "sport_type", None)) == "strength")
    count += sum(
        1
        for session in planned_sessions
        if _sport_bucket(getattr(session, "sport_type", None)) == "strength"
        and getattr(session, "manual_completed", False)
        and not getattr(session, "matched", False)
        and getattr(session, "linked_activity_id", None) is None
    )
    return count


def _sport_bucket(value: str | None) -> str:
    normalized = _normalize_sport_value(value)
    if normalized in {"running", "trail_running"}:
        return "running"
    if normalized in {"cycling", "mtb"}:
        return "cycling"
    if normalized == "strength":
        return "strength"
    return "other"


def _build_week_load_intensity_payload(context: Any, metrics: dict[str, Any]) -> dict[str, Any]:
    activities = list(getattr(context, "activities", []) or [])
    hard_count = 0
    high_aerobic_count = 0
    anaerobic_count = 0
    flags: list[str] = []
    for activity in activities:
        if _is_hard_week_activity(activity):
            hard_count += 1
        if (getattr(activity, "training_effect_aerobic", None) or 0) >= 4.0:
            high_aerobic_count += 1
        if (getattr(activity, "training_effect_anaerobic", None) or 0) >= 2.0:
            anaerobic_count += 1
    if high_aerobic_count >= 2:
        flags.append("multiple_high_aerobic_te")
    if hard_count >= 3:
        flags.append("many_hard_activities")
    if _total_training_load(activities) >= 350:
        flags.append("high_weekly_training_load")
    if metrics.get("derived_flags", {}).get("intensity_distribution_imbalance_flag"):
        flags.append("intensity_distribution_imbalance")
    return {
        "hard_activities_count": hard_count,
        "high_aerobic_te_count": high_aerobic_count,
        "anaerobic_stimulus_count": anaerobic_count,
        "estimated_distribution": _estimated_distribution_label(metrics),
        "flags": flags,
    }


def _is_hard_week_activity(activity: Any) -> bool:
    if (getattr(activity, "training_effect_anaerobic", None) or 0) >= 2.5:
        return True
    if (getattr(activity, "training_effect_aerobic", None) or 0) >= 4.0:
        return True
    if (getattr(activity, "training_load", None) or 0) >= 150:
        return True
    return False


def _estimated_distribution_label(metrics: dict[str, Any]) -> str:
    summary = metrics.get("distribution", {}).get("intensity_zone_summary", {}) or {}
    pct_z2 = summary.get("pct_z2")
    pct_z4_plus = summary.get("pct_z4_plus")
    pct_z3 = summary.get("pct_z3")
    if pct_z2 is None and pct_z4_plus is None and pct_z3 is None:
        return "insufficient_data"
    if (pct_z4_plus or 0) > 25 or ((pct_z3 or 0) + (pct_z4_plus or 0)) > 60:
        return "intensity_heavy"
    if (pct_z2 or 0) >= 40 and (pct_z4_plus or 0) <= 20:
        return "mostly_aerobic"
    return "mixed"


def _build_week_load_health_payload(db: Session, athlete_id: int, start_date: date, end_date: date) -> dict[str, Any]:
    metrics = list(
        db.scalars(
            select(DailyHealthMetric)
            .where(
                DailyHealthMetric.athlete_id == athlete_id,
                DailyHealthMetric.metric_date >= start_date,
                DailyHealthMetric.metric_date <= end_date,
            )
            .order_by(DailyHealthMetric.metric_date.asc(), DailyHealthMetric.id.asc())
        ).all()
    )
    if not metrics:
        return {
            "days_available": 0,
            "avg_readiness_score": None,
            "avg_sleep_minutes": None,
            "avg_body_battery_morning": None,
            "avg_hrv": None,
            "main_limiters": [],
        }
    readiness_scores: list[float] = []
    main_limiters: list[str] = []
    for metric in metrics:
        evaluation = evaluate_health_readiness(build_health_readiness_summary(db, athlete_id, metric.metric_date))
        if evaluation.readiness_score is not None:
            readiness_scores.append(float(evaluation.readiness_score))
        if evaluation.main_limiter:
            main_limiters.append(str(evaluation.main_limiter))
    return {
        "days_available": len(metrics),
        "avg_readiness_score": round(sum(readiness_scores) / len(readiness_scores), 1) if readiness_scores else None,
        "avg_sleep_minutes": _average_numeric([item.sleep_duration_minutes for item in metrics]),
        "avg_body_battery_morning": _average_numeric([item.body_battery_morning or item.body_battery_start for item in metrics]),
        "avg_hrv": _average_numeric([item.hrv_value or item.hrv_avg_ms for item in metrics]),
        "main_limiters": sorted(set(main_limiters)),
    }


def _average_numeric(values: list[float | int | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 1)


def _build_week_load_weekly_analysis_payload(analysis: WeeklyAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "summary": analysis.summary_short or analysis.coach_conclusion,
        "risk_level": _weekly_risk_level(analysis),
        "recommendation": analysis.next_week_recommendation,
    }


def _build_previous_week_summary_payload(current_start: date, context: Any, metrics: dict[str, Any]) -> dict[str, Any]:
    week_payload = _build_week_load_week_payload(context, metrics)
    del current_start
    return {
        "start_date": context.week_start_date.isoformat(),
        "total_duration_sec": week_payload["total_duration_sec"],
        "total_distance_m": week_payload["total_distance_m"],
        "total_training_load": week_payload["total_training_load"],
        "delta_training_load": None,
        "delta_duration_sec": None,
        "delta_distance_m": None,
    }


def _resolve_session_payload_analysis(
    db: Session,
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
) -> SessionAnalysis | None:
    if planned_session is not None:
        linked_activity_id = activity.id if activity is not None else (
            planned_session.activity_match.garmin_activity_id_fk
            if planned_session.activity_match is not None else None
        )
        analysis = _get_preferred_session_analysis(db, planned_session.id, linked_activity_id)
        if analysis is not None:
            return analysis
    return _resolve_session_analysis(activity, planned_session)


def _serialize_analysis_payload_planned_session(session: PlannedSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    metrics = derive_session_metrics(session)
    return {
        "id": session.id,
        "name": session.name,
        "date": session.training_day.day_date.isoformat() if session.training_day and session.training_day.day_date else None,
        "sport": session.sport_type,
        "modality": session.modality,
        "planned_duration_sec": metrics.duration_sec,
        "planned_distance_m": metrics.distance_m,
        "notes": session.target_notes or session.description_text,
    }


def _serialize_analysis_payload_planned_steps(session: PlannedSession | None) -> list[dict[str, Any]]:
    if session is None:
        return []
    return [
        {
            "id": step.id,
            "step_order": step.step_order,
            "repeat_group": step.repeat_count,
            "duration_sec": step.duration_sec,
            "distance_m": step.distance_m,
            "target_type": step.target_type,
            "target_hr_zone": step.target_hr_zone,
            "target_hr_min": step.target_hr_min,
            "target_hr_max": step.target_hr_max,
            "target_pace_zone": step.target_pace_zone,
            "target_pace_min_sec_km": step.target_pace_min_sec_km,
            "target_pace_max_sec_km": step.target_pace_max_sec_km,
            "target_notes": step.target_notes,
        }
        for step in session.planned_session_steps
    ]


def _serialize_analysis_payload_activity(activity: GarminActivity | None) -> dict[str, Any] | None:
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
        "avg_power": activity.avg_power,
        "normalized_power": activity.normalized_power,
        "avg_cadence": activity.avg_cadence,
        "training_load": activity.training_load,
        "training_effect_aerobic": activity.training_effect_aerobic,
        "training_effect_anaerobic": activity.training_effect_anaerobic,
    }


def _serialize_analysis_payload_laps(activity: GarminActivity | None) -> list[dict[str, Any]]:
    if activity is None:
        return []
    return [
        {
            "lap_number": lap.lap_number,
            "lap_type": lap.lap_type,
            "duration_sec": lap.duration_sec,
            "distance_m": lap.distance_m,
            "avg_hr": lap.avg_hr,
            "max_hr": lap.max_hr,
            "avg_pace_sec_km": lap.avg_pace_sec_km,
            "avg_power": lap.avg_power,
            "avg_cadence": lap.avg_cadence,
        }
        for lap in sorted(activity.laps, key=lambda item: (item.lap_number, item.id))
    ]


def _serialize_step_vs_lap_comparison(technical_view: dict[str, Any]) -> list[dict[str, Any]]:
    rows = technical_view.get("matching_rows") or []
    return [
        {
            "step_order": row.get("step_order"),
            "lap_number": row.get("lap_index"),
            "planned": row.get("planned"),
            "real": row.get("actual"),
            "status": row.get("status"),
            "reason": row.get("reason"),
            "penalties": {
                "summary": row.get("penalties"),
                "total_penalty": row.get("total_penalty"),
            },
            "discarded": _normalize_discarded_candidates(row.get("rejected")),
        }
        for row in rows
    ]


def _normalize_discarded_candidates(value: Any) -> list[str]:
    if value in (None, "", "-"):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _build_session_payload_data_quality(
    *,
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
    analysis: SessionAnalysis | None,
    technical_view: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[str] = []
    has_laps = bool(activity is not None and getattr(activity, "laps", []))
    has_metrics_json = bool(technical_view.get("metrics_json"))
    has_llm_json = bool(technical_view.get("llm_json"))
    if planned_session is None:
        warnings.append("No hay sesion programada resuelta para este payload.")
    if activity is None:
        warnings.append("No hay actividad resuelta para este payload.")
    if activity is not None and not has_laps:
        warnings.append("La actividad no tiene laps cargados.")
    if analysis is None:
        warnings.append("No hay SessionAnalysis guardado para esta combinacion sesion-actividad.")
    if analysis is not None and not has_metrics_json:
        warnings.append("El SessionAnalysis existe pero no tiene metrics_json disponible.")
    if analysis is not None and not has_llm_json:
        warnings.append("El SessionAnalysis existe pero no tiene llm_json disponible.")
    return {
        "has_planned_session": planned_session is not None,
        "has_activity": activity is not None,
        "has_laps": has_laps,
        "has_metrics_json": has_metrics_json,
        "has_llm_json": has_llm_json,
        "warnings": warnings,
    }


def _build_week_load_data_quality(context: Any, weekly_analysis: WeeklyAnalysis | None, health_payload: dict[str, Any]) -> dict[str, Any]:
    has_garmin_activities = bool(getattr(context, "activities", []) or [])
    has_manual_sessions = bool(_serialize_manual_week_sessions(context))
    has_completed_training = has_garmin_activities or has_manual_sessions
    has_planned = bool(getattr(context, "planned_sessions", []) or [])
    has_health = bool(health_payload.get("days_available"))
    warnings: list[str] = []
    if not has_completed_training:
        warnings.append("No hay entrenamientos realizados cargados para esa semana.")
    elif not has_garmin_activities:
        warnings.append("No hay actividades Garmin para esa semana; el resumen usa sesiones manuales completadas.")
    if not has_planned:
        warnings.append("No hay sesiones planificadas cargadas para esa semana.")
    if not has_health:
        warnings.append("Hay pocos o ningun dato de salud para esa semana.")
    if weekly_analysis is None:
        warnings.append("No hay weekly_analysis guardado para esa semana.")
    return {
        "has_activities": has_completed_training,
        "has_garmin_activities": has_garmin_activities,
        "has_manual_sessions": has_manual_sessions,
        "has_completed_training": has_completed_training,
        "has_planned_sessions": has_planned,
        "has_health": has_health,
        "has_weekly_analysis": weekly_analysis is not None,
        "warnings": warnings,
    }


def _build_week_load_recommendation(
    *,
    week_payload: dict[str, Any],
    intensity_payload: dict[str, Any],
    health_payload: dict[str, Any],
    weekly_analysis: WeeklyAnalysis | None,
    previous_summary: dict[str, Any] | None,
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    status = "balanced"
    reasons: list[str] = []
    next_step = "Mantener el seguimiento de la carga y revisar sensaciones en los proximos dias."

    if not data_quality.get("has_completed_training"):
        return {
            "status": "no_data",
            "summary": "No hay actividades suficientes para construir un resumen de carga semanal.",
            "reasons": ["La semana no tiene entrenamientos registrados."],
            "next_step": "Sincronizar actividades o revisar la semana consultada.",
        }

    current_load = float(week_payload.get("total_training_load") or 0)
    planned = int(week_payload.get("planned_sessions_count") or 0)
    completed = int(week_payload.get("completed_sessions_count") or 0)
    avg_readiness = health_payload.get("avg_readiness_score")
    hard_count = int(intensity_payload.get("hard_activities_count") or 0)
    high_aerobic = int(intensity_payload.get("high_aerobic_te_count") or 0)

    if previous_summary is not None:
        prev_load = float(previous_summary.get("total_training_load") or 0)
        previous_summary["delta_training_load"] = round(current_load - prev_load, 1)
        previous_summary["delta_duration_sec"] = int((week_payload.get("total_duration_sec") or 0) - (previous_summary.get("total_duration_sec") or 0))
        previous_summary["delta_distance_m"] = round(float(week_payload.get("total_distance_m") or 0) - float(previous_summary.get("total_distance_m") or 0), 1)
        if prev_load > 0 and current_load >= prev_load * 1.25:
            status = "building"
            reasons.append("La carga subio de forma marcada versus la semana anterior.")
        if prev_load > 0 and current_load >= prev_load * 1.5:
            status = "high_load"
            reasons.append("La carga semanal salto muy por encima de la semana anterior.")

    if high_aerobic >= 2 or hard_count >= 3 or "high_weekly_training_load" in intensity_payload.get("flags", []):
        if status == "balanced":
            status = "high_load"
        reasons.append("Se acumularon varias sesiones exigentes o una carga alta.")

    if planned > 0 and completed < max(1, planned // 2):
        status = "underloaded"
        reasons.append("La carga realizada quedo baja respecto de lo planificado.")
        next_step = "Revisar si hubo recortes por agenda, fatiga o falta de sincronizacion."

    if avg_readiness is not None and avg_readiness < 65 and status in {"high_load", "building", "balanced"}:
        status = "recovery_needed"
        reasons.append("La carga semanal se combina con readiness promedio bajo.")
        next_step = "Priorizar descarga, trabajo facil o recuperacion antes de volver a exigir."

    if weekly_analysis is not None and _weekly_risk_level(weekly_analysis) == "high" and status == "balanced":
        status = "high_load"
        reasons.append("El weekly_analysis marca riesgo alto de carga o fatiga.")

    if not reasons:
        reasons.append("La carga semanal aparece razonable y sin alertas fuertes en los datos disponibles.")

    summary_map = {
        "balanced": "La semana se ve bastante equilibrada.",
        "building": "La semana viene en construccion, con una carga en aumento.",
        "high_load": "La semana esta cargada y conviene vigilar la acumulacion de intensidad.",
        "underloaded": "La semana quedo por debajo de lo esperado.",
        "recovery_needed": "La semana sugiere necesidad de descarga o recuperacion.",
        "no_data": "No hay datos suficientes para resumir la carga semanal.",
    }
    return {
        "status": status,
        "summary": summary_map.get(status, "Resumen semanal disponible."),
        "reasons": reasons,
        "next_step": next_step,
    }
