from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import logging
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.athlete import Athlete
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.services.analysis_v2.scoring import average_scores, clamp_score
from app.services.analysis_v2.weekly_narrative import generate_weekly_narrative as _generate_weekly_narrative


logger = logging.getLogger(__name__)

ANALYSIS_VERSION = "v2"
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_WARNINGS = "completed_with_warnings"
STATUS_ERROR = "error"

PREVIOUS_WEEKS_TO_COMPARE = 3
OVERLOAD_DURATION_RATIO = 1.25
UNDERTRAINING_DURATION_RATIO = 0.60
POOR_DISTRIBUTION_PEAK_SHARE_PCT = 45.0
LOW_CONSISTENCY_SCORE_THRESHOLD = 60.0
HIGH_FATIGUE_SCORE_THRESHOLD = 75.0


@dataclass(slots=True)
class WeeklyAthleteContext:
    id: int
    name: str | None
    primary_sport: str | None
    max_hr: int | None
    resting_hr: int | None
    vo2max: float | None


@dataclass(slots=True)
class WeeklyActivityContext:
    activity_id: int
    garmin_activity_id: int
    activity_date: date | None
    start_time: str | None
    title: str | None
    sport_type: str | None
    discipline_variant: str | None
    duration_sec: int | None
    distance_m: float | None
    elevation_gain_m: float | None
    avg_hr: int | None
    avg_pace_sec_km: float | None
    avg_power: int | None
    avg_cadence: float | None
    matched_planned_session_id: int | None
    planned_session_title: str | None
    session_analysis_id: int | None
    session_analysis_summary: str | None
    session_compliance_score: float | None
    session_execution_score: float | None
    session_control_score: float | None
    session_fatigue_score: float | None


@dataclass(slots=True)
class WeeklyPlannedSessionContext:
    planned_session_id: int
    session_date: date | None
    title: str
    sport_type: str | None
    session_type: str | None
    expected_duration_min: int | None
    expected_distance_km: float | None
    target_type: str | None
    target_hr_zone: str | None
    target_pace_zone: str | None
    target_power_zone: str | None
    target_rpe_zone: str | None
    is_key_session: bool
    matched: bool
    linked_activity_id: int | None


@dataclass(slots=True)
class WeeklySessionAnalysisContext:
    session_analysis_id: int
    planned_session_id: int
    activity_id: int
    status: str
    summary_short: str | None
    compliance_score: float | None
    execution_score: float | None
    control_score: float | None
    fatigue_score: float | None
    metrics_json: dict[str, Any] | None


@dataclass(slots=True)
class WeeklyHealthDayContext:
    metric_date: date
    sleep_hours: float | None
    sleep_score: int | None
    stress_avg: int | None
    body_battery_end: int | None
    hrv_avg_ms: float | None
    recovery_time_hours: float | None
    resting_hr: int | None


@dataclass(slots=True)
class PreviousWeekSummaryContext:
    week_start_date: date
    week_end_date: date
    activity_count: int
    total_duration_sec: int
    total_distance_m: float
    total_elevation_gain_m: float
    planned_sessions: int
    completed_sessions: int
    compliance_ratio: float | None


@dataclass(slots=True)
class WeeklyContext:
    athlete: WeeklyAthleteContext
    reference_date: date
    week_start_date: date
    week_end_date: date
    activities: list[WeeklyActivityContext] = field(default_factory=list)
    planned_sessions: list[WeeklyPlannedSessionContext] = field(default_factory=list)
    session_analyses: list[WeeklySessionAnalysisContext] = field(default_factory=list)
    health_days: list[WeeklyHealthDayContext] = field(default_factory=list)
    previous_weeks: list[PreviousWeekSummaryContext] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_week_context(db: Session, athlete_id: int, reference_date: date | str | datetime) -> WeeklyContext:
    normalized_reference_date = _coerce_date(reference_date)
    week_start_date = _week_start(normalized_reference_date)
    week_end_date = week_start_date + timedelta(days=6)
    history_start = week_start_date - timedelta(days=7 * PREVIOUS_WEEKS_TO_COMPARE)

    logger.info(
        "Building WeeklyContext athlete_id=%s reference_date=%s week_start=%s week_end=%s",
        athlete_id,
        normalized_reference_date.isoformat(),
        week_start_date.isoformat(),
        week_end_date.isoformat(),
    )

    athlete = db.scalar(
        select(Athlete)
        .where(Athlete.id == athlete_id)
        .options(selectinload(Athlete.training_plans))
    )
    if athlete is None:
        raise ValueError(f"No se encontro Athlete #{athlete_id}.")

    all_activities = list(
        db.scalars(
            select(GarminActivity)
            .where(
                GarminActivity.athlete_id == athlete_id,
                GarminActivity.start_time.is_not(None),
            )
            .options(
                selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
                selectinload(GarminActivity.session_analyses),
            )
            .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
        ).all()
    )
    history_activities = [
        activity
        for activity in all_activities
        if _activity_local_date(activity) is not None and history_start <= _activity_local_date(activity) <= week_end_date
    ]
    weekly_activities = [
        activity
        for activity in history_activities
        if week_start_date <= _activity_local_date(activity) <= week_end_date
    ]

    all_planned_sessions = list(
        db.scalars(
            select(PlannedSession)
            .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
            .where(
                PlannedSession.athlete_id == athlete_id,
                TrainingDay.day_date >= history_start,
                TrainingDay.day_date <= week_end_date,
            )
            .options(
                selectinload(PlannedSession.activity_match),
                selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            )
            .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc())
        ).all()
    )
    weekly_planned_sessions = [
        session
        for session in all_planned_sessions
        if session.training_day and week_start_date <= session.training_day.day_date <= week_end_date
    ]

    session_analyses = list(
        db.scalars(
            select(SessionAnalysis)
            .where(
                SessionAnalysis.athlete_id == athlete_id,
                SessionAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .order_by(SessionAnalysis.analyzed_at.desc(), SessionAnalysis.id.desc())
        ).all()
    )
    analysis_by_activity: dict[int, SessionAnalysis] = {}
    for analysis in session_analyses:
        analysis_date = _analysis_date(analysis, history_activities, all_planned_sessions)
        if analysis_date is None or not (week_start_date <= analysis_date <= week_end_date):
            continue
        analysis_by_activity.setdefault(analysis.activity_id, analysis)

    weekly_health_days = list(
        db.scalars(
            select(DailyHealthMetric)
            .where(
                DailyHealthMetric.athlete_id == athlete_id,
                DailyHealthMetric.metric_date >= week_start_date,
                DailyHealthMetric.metric_date <= week_end_date,
            )
            .order_by(DailyHealthMetric.metric_date.asc())
        ).all()
    )

    context = WeeklyContext(
        athlete=WeeklyAthleteContext(
            id=athlete.id,
            name=athlete.name,
            primary_sport=_infer_primary_sport(athlete),
            max_hr=athlete.max_hr,
            resting_hr=athlete.resting_hr,
            vo2max=athlete.vo2max,
        ),
        reference_date=normalized_reference_date,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
        activities=[
            _build_weekly_activity_context(activity, analysis_by_activity.get(activity.id))
            for activity in weekly_activities
        ],
        planned_sessions=[_build_weekly_planned_session_context(session) for session in weekly_planned_sessions],
        session_analyses=[_build_weekly_session_analysis_context(item) for item in analysis_by_activity.values()],
        health_days=[_build_weekly_health_context(item) for item in weekly_health_days],
        previous_weeks=_build_previous_week_summaries(history_activities, all_planned_sessions, week_start_date),
    )
    logger.info(
        "WeeklyContext built athlete_id=%s activities=%s planned_sessions=%s session_analyses=%s previous_weeks=%s",
        athlete_id,
        len(context.activities),
        len(context.planned_sessions),
        len(context.session_analyses),
        len(context.previous_weeks),
    )
    return context


def compute_week_metrics(context: WeeklyContext) -> dict[str, Any]:
    totals = _build_week_totals(context)
    distribution = _build_week_distribution(context)
    compliance = _build_week_compliance(context)
    trends = _build_week_trends(context, totals)
    consistency = _build_week_consistency(context, totals)
    health_context = _build_week_health_metrics(context)
    session_aggregate = _build_session_analysis_aggregate(context)
    derived_flags = _build_week_flags(context, totals, distribution, compliance, trends, consistency, health_context, session_aggregate)
    scores = _build_week_scores(context, totals, distribution, compliance, trends, consistency, health_context, session_aggregate)

    return {
        "totals": totals,
        "distribution": distribution,
        "compliance": compliance,
        "trends": trends,
        "consistency": consistency,
        "health_context": health_context,
        "session_analysis_aggregate": session_aggregate,
        "derived_flags": derived_flags,
        "scores": scores,
        "rule_thresholds": _weekly_thresholds(),
        "formula": {
            "load_score": "promedio entre cercania al volumen reciente y cumplimiento semanal",
            "consistency_score": "promedio entre dias entrenados, distribucion diaria y cumplimiento",
            "fatigue_score": "promedio entre fatiga de sesiones, componente de carga semanal, sesiones duras y salud si existe",
            "balance_score": "promedio entre equilibrio por deporte y reparto de intensidades",
        },
    }


def generate_weekly_narrative(context: WeeklyContext, metrics: dict[str, Any]):
    return _generate_weekly_narrative(context, metrics)


def run_weekly_analysis(
    db: Session,
    athlete_id: int,
    reference_date: date | str | datetime,
    trigger_source: str = "auto",
) -> WeeklyAnalysis:
    normalized_reference_date = _coerce_date(reference_date)
    week_start_date = _week_start(normalized_reference_date)
    week_end_date = week_start_date + timedelta(days=6)

    logger.info(
        "Starting WeeklyAnalysis V2 pipeline athlete_id=%s week_start=%s trigger_source=%s",
        athlete_id,
        week_start_date.isoformat(),
        trigger_source,
    )

    analysis = _prepare_pending_weekly_analysis(
        db,
        athlete_id=athlete_id,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
        trigger_source=trigger_source,
    )

    try:
        logger.info("WeeklyAnalysis V2 build_week_context started analysis_id=%s", analysis.id)
        context = build_week_context(db, athlete_id, normalized_reference_date)
        logger.info("WeeklyAnalysis V2 build_week_context completed analysis_id=%s", analysis.id)
    except Exception as exc:
        logger.exception(
            "WeeklyAnalysis V2 build_week_context failed analysis_id=%s athlete_id=%s",
            analysis.id,
            athlete_id,
        )
        return _mark_weekly_analysis_error(db, analysis.id, f"build_week_context failed: {exc}")

    try:
        logger.info("WeeklyAnalysis V2 compute_week_metrics started analysis_id=%s", analysis.id)
        metrics = compute_week_metrics(context)
        logger.info("WeeklyAnalysis V2 compute_week_metrics completed analysis_id=%s", analysis.id)
    except Exception as exc:
        logger.exception(
            "WeeklyAnalysis V2 compute_week_metrics failed analysis_id=%s athlete_id=%s",
            analysis.id,
            athlete_id,
        )
        return _mark_weekly_analysis_error(db, analysis.id, f"compute_week_metrics failed: {exc}")

    metrics_payload = {
        "context": _to_jsonable(context.to_dict()),
        "metrics": _to_jsonable(metrics),
    }

    try:
        logger.info("WeeklyAnalysis V2 generate_weekly_narrative started analysis_id=%s", analysis.id)
        narrative = generate_weekly_narrative(context, metrics)
        logger.info(
            "WeeklyAnalysis V2 generate_weekly_narrative completed analysis_id=%s narrative_status=%s",
            analysis.id,
            narrative.narrative_status,
        )
    except Exception as exc:
        logger.exception(
            "WeeklyAnalysis V2 generate_weekly_narrative failed analysis_id=%s athlete_id=%s",
            analysis.id,
            athlete_id,
        )
        narrative = _weekly_fallback_narrative_from_exception(exc)

    final_status = STATUS_COMPLETED if narrative.narrative_status == "completed" else STATUS_COMPLETED_WITH_WARNINGS
    refreshed = db.get(WeeklyAnalysis, analysis.id)
    if refreshed is None:
        raise ValueError(f"No se pudo recuperar WeeklyAnalysis #{analysis.id}.")

    totals = metrics["totals"]
    distribution = metrics["distribution"]
    compliance = metrics["compliance"]
    scores = metrics["scores"]
    flags = metrics["derived_flags"]

    refreshed.status = final_status
    refreshed.analysis_version = ANALYSIS_VERSION
    refreshed.analyzed_at = datetime.now(timezone.utc)
    refreshed.error_message = narrative.error_message
    refreshed.summary_short = narrative.summary_short
    refreshed.analysis_natural = narrative.analysis_natural
    refreshed.coach_conclusion = narrative.coach_conclusion
    refreshed.next_week_recommendation = narrative.next_week_recommendation
    refreshed.total_duration_sec = totals["total_duration_sec"]
    refreshed.total_distance_m = totals["total_distance_m"]
    refreshed.total_elevation_gain_m = totals["total_elevation_gain_m"]
    refreshed.total_sessions = totals["activity_count"]
    refreshed.sessions_by_sport = distribution["sessions_by_sport"]
    refreshed.time_in_zones = distribution["time_in_zones_sec"]
    refreshed.intensity_distribution = distribution["intensity_distribution"]
    refreshed.planned_sessions = compliance["planned_sessions"]
    refreshed.completed_sessions = compliance["completed_sessions"]
    refreshed.compliance_ratio = compliance["compliance_ratio"]
    refreshed.load_score = scores["load_score"]
    refreshed.consistency_score = scores["consistency_score"]
    refreshed.fatigue_score = scores["fatigue_score"]
    refreshed.balance_score = scores["balance_score"]
    refreshed.metrics_json = metrics_payload
    refreshed.llm_json = narrative.llm_json | {
        "structured_output": narrative.structured_output.model_dump(),
        "derived_flags": flags,
    }

    db.add(refreshed)
    db.commit()
    db.refresh(refreshed)
    logger.info(
        "WeeklyAnalysis V2 pipeline completed analysis_id=%s status=%s",
        refreshed.id,
        refreshed.status,
    )
    return refreshed


def re_run_weekly_analysis(
    db: Session,
    athlete_id: int,
    reference_date: date | str | datetime,
    trigger_source: str = "manual_reanalysis",
) -> WeeklyAnalysis:
    logger.info(
        "Re-running WeeklyAnalysis V2 athlete_id=%s reference_date=%s trigger_source=%s",
        athlete_id,
        _coerce_date(reference_date).isoformat(),
        trigger_source,
    )
    return run_weekly_analysis(
        db,
        athlete_id=athlete_id,
        reference_date=reference_date,
        trigger_source=trigger_source,
    )


def trigger_weekly_analysis(
    db: Session,
    athlete_id: int,
    reference_date: date | str | datetime,
    trigger_source: str = "auto",
) -> WeeklyAnalysis | None:
    try:
        return run_weekly_analysis(
            db,
            athlete_id=athlete_id,
            reference_date=reference_date,
            trigger_source=trigger_source,
        )
    except Exception:
        logger.exception(
            "WeeklyAnalysis V2 trigger failed athlete_id=%s reference_date=%s trigger_source=%s",
            athlete_id,
            _coerce_date(reference_date).isoformat(),
            trigger_source,
        )
        return None


def _prepare_pending_weekly_analysis(
    db: Session,
    *,
    athlete_id: int,
    week_start_date: date,
    week_end_date: date,
    trigger_source: str,
) -> WeeklyAnalysis:
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise ValueError(f"No se encontro Athlete #{athlete_id}.")

    existing = list(
        db.scalars(
            select(WeeklyAnalysis)
            .where(
                WeeklyAnalysis.athlete_id == athlete_id,
                WeeklyAnalysis.week_start_date == week_start_date,
                WeeklyAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .order_by(WeeklyAnalysis.id.desc())
        ).all()
    )

    if existing:
        analysis = existing[0]
        for duplicate in existing[1:]:
            db.delete(duplicate)
    else:
        analysis = WeeklyAnalysis(
            athlete_id=athlete_id,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            analysis_version=ANALYSIS_VERSION,
        )

    analysis.athlete_id = athlete_id
    analysis.week_start_date = week_start_date
    analysis.week_end_date = week_end_date
    analysis.analysis_version = ANALYSIS_VERSION
    analysis.status = STATUS_PENDING
    analysis.analyzed_at = None
    analysis.error_message = None
    analysis.summary_short = None
    analysis.analysis_natural = None
    analysis.coach_conclusion = None
    analysis.next_week_recommendation = None
    analysis.total_duration_sec = None
    analysis.total_distance_m = None
    analysis.total_elevation_gain_m = None
    analysis.total_sessions = None
    analysis.sessions_by_sport = None
    analysis.time_in_zones = None
    analysis.intensity_distribution = None
    analysis.planned_sessions = None
    analysis.completed_sessions = None
    analysis.compliance_ratio = None
    analysis.load_score = None
    analysis.consistency_score = None
    analysis.fatigue_score = None
    analysis.balance_score = None
    analysis.metrics_json = None
    analysis.llm_json = {
        "provider": None,
        "model": None,
        "status": STATUS_PENDING,
        "trigger_source": trigger_source,
    }

    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _mark_weekly_analysis_error(db: Session, analysis_id: int, error_message: str) -> WeeklyAnalysis:
    db.rollback()
    analysis = db.get(WeeklyAnalysis, analysis_id)
    if analysis is None:
        raise ValueError(f"No se pudo recuperar WeeklyAnalysis #{analysis_id}.")

    analysis.status = STATUS_ERROR
    analysis.analyzed_at = datetime.now(timezone.utc)
    analysis.error_message = error_message
    analysis.llm_json = {
        **(analysis.llm_json or {}),
        "status": STATUS_ERROR,
        "error_message": error_message,
    }
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    logger.error("WeeklyAnalysis V2 marked as error analysis_id=%s error=%s", analysis.id, error_message)
    return analysis


def _weekly_fallback_narrative_from_exception(exc: Exception):
    from app.services.analysis_v2.weekly_schemas import WeeklyNarrativeResult, WeeklyNarrativeStructuredOutput

    return WeeklyNarrativeResult(
        narrative_status="error",
        provider=None,
        model=None,
        summary_short="Analisis semanal incompleto",
        analysis_natural="No se pudo generar la interpretacion automatica de la semana, pero las metricas objetivas si quedaron calculadas.",
        coach_conclusion="La lectura semanal queda pendiente por un fallo tecnico en esta ejecucion.",
        next_week_recommendation="Reintentar el analisis semanal cuando el servicio narrativo vuelva a estar disponible.",
        structured_output=WeeklyNarrativeStructuredOutput(),
        llm_json={
            "provider": None,
            "model": None,
            "status": STATUS_ERROR,
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        },
        error_message=str(exc),
    )


def _build_weekly_activity_context(
    activity: GarminActivity,
    analysis: SessionAnalysis | None,
) -> WeeklyActivityContext:
    match = activity.activity_match
    planned_session = match.planned_session if match else None
    return WeeklyActivityContext(
        activity_id=activity.id,
        garmin_activity_id=activity.garmin_activity_id,
        activity_date=_activity_local_date(activity),
        start_time=activity.start_time.isoformat() if activity.start_time else None,
        title=activity.activity_name,
        sport_type=activity.sport_type,
        discipline_variant=activity.discipline_variant,
        duration_sec=activity.duration_sec,
        distance_m=activity.distance_m,
        elevation_gain_m=activity.elevation_gain_m,
        avg_hr=activity.avg_hr,
        avg_pace_sec_km=activity.avg_pace_sec_km,
        avg_power=activity.avg_power,
        avg_cadence=activity.avg_cadence,
        matched_planned_session_id=planned_session.id if planned_session else None,
        planned_session_title=planned_session.name if planned_session else None,
        session_analysis_id=analysis.id if analysis else None,
        session_analysis_summary=analysis.summary_short if analysis else None,
        session_compliance_score=analysis.compliance_score if analysis else None,
        session_execution_score=analysis.execution_score if analysis else None,
        session_control_score=analysis.control_score if analysis else None,
        session_fatigue_score=analysis.fatigue_score if analysis else None,
    )


def _build_weekly_planned_session_context(session: PlannedSession) -> WeeklyPlannedSessionContext:
    return WeeklyPlannedSessionContext(
        planned_session_id=session.id,
        session_date=session.training_day.day_date if session.training_day else None,
        title=session.name,
        sport_type=session.sport_type,
        session_type=session.session_type,
        expected_duration_min=session.expected_duration_min,
        expected_distance_km=session.expected_distance_km,
        target_type=session.target_type,
        target_hr_zone=session.target_hr_zone,
        target_pace_zone=session.target_pace_zone,
        target_power_zone=session.target_power_zone,
        target_rpe_zone=session.target_rpe_zone,
        is_key_session=session.is_key_session,
        matched=session.activity_match is not None,
        linked_activity_id=session.activity_match.garmin_activity_id_fk if session.activity_match else None,
    )


def _build_weekly_session_analysis_context(analysis: SessionAnalysis) -> WeeklySessionAnalysisContext:
    return WeeklySessionAnalysisContext(
        session_analysis_id=analysis.id,
        planned_session_id=analysis.planned_session_id,
        activity_id=analysis.activity_id,
        status=analysis.status,
        summary_short=analysis.summary_short,
        compliance_score=analysis.compliance_score,
        execution_score=analysis.execution_score,
        control_score=analysis.control_score,
        fatigue_score=analysis.fatigue_score,
        metrics_json=analysis.metrics_json if isinstance(analysis.metrics_json, dict) else None,
    )


def _build_weekly_health_context(item: DailyHealthMetric) -> WeeklyHealthDayContext:
    return WeeklyHealthDayContext(
        metric_date=item.metric_date,
        sleep_hours=item.sleep_hours,
        sleep_score=item.sleep_score,
        stress_avg=item.stress_avg,
        body_battery_end=item.body_battery_end,
        hrv_avg_ms=item.hrv_avg_ms,
        recovery_time_hours=item.recovery_time_hours,
        resting_hr=item.resting_hr,
    )


def _build_previous_week_summaries(
    history_activities: list[GarminActivity],
    all_planned_sessions: list[PlannedSession],
    current_week_start: date,
) -> list[PreviousWeekSummaryContext]:
    previous_summaries: list[PreviousWeekSummaryContext] = []
    for offset in range(1, PREVIOUS_WEEKS_TO_COMPARE + 1):
        week_start = current_week_start - timedelta(days=7 * offset)
        week_end = week_start + timedelta(days=6)
        week_activities = [
            item
            for item in history_activities
            if _activity_local_date(item) is not None and week_start <= _activity_local_date(item) <= week_end
        ]
        week_planned = [
            item
            for item in all_planned_sessions
            if item.training_day and week_start <= item.training_day.day_date <= week_end
        ]
        completed_sessions = sum(1 for item in week_planned if item.activity_match is not None)
        compliance_ratio = None
        if week_planned:
            compliance_ratio = round(completed_sessions / len(week_planned), 3)
        previous_summaries.append(
            PreviousWeekSummaryContext(
                week_start_date=week_start,
                week_end_date=week_end,
                activity_count=len(week_activities),
                total_duration_sec=sum(item.duration_sec or 0 for item in week_activities),
                total_distance_m=round(sum(item.distance_m or 0.0 for item in week_activities), 2),
                total_elevation_gain_m=round(sum(item.elevation_gain_m or 0.0 for item in week_activities), 2),
                planned_sessions=len(week_planned),
                completed_sessions=completed_sessions,
                compliance_ratio=compliance_ratio,
            )
        )
    previous_summaries.sort(key=lambda item: item.week_start_date)
    return previous_summaries


def _build_week_totals(context: WeeklyContext) -> dict[str, Any]:
    daily_duration_sec: dict[str, int] = {}
    daily_distance_m: dict[str, float] = {}
    daily_elevation_m: dict[str, float] = {}
    for activity in context.activities:
        if activity.activity_date is None:
            continue
        key = activity.activity_date.isoformat()
        daily_duration_sec[key] = daily_duration_sec.get(key, 0) + (activity.duration_sec or 0)
        daily_distance_m[key] = round(daily_distance_m.get(key, 0.0) + (activity.distance_m or 0.0), 2)
        daily_elevation_m[key] = round(daily_elevation_m.get(key, 0.0) + (activity.elevation_gain_m or 0.0), 2)

    return {
        "activity_count": len(context.activities),
        "total_duration_sec": sum(activity.duration_sec or 0 for activity in context.activities),
        "total_distance_m": round(sum(activity.distance_m or 0.0 for activity in context.activities), 2),
        "total_elevation_gain_m": round(sum(activity.elevation_gain_m or 0.0 for activity in context.activities), 2),
        "daily_duration_sec": daily_duration_sec,
        "daily_distance_m": daily_distance_m,
        "daily_elevation_m": daily_elevation_m,
    }


def _build_week_distribution(context: WeeklyContext) -> dict[str, Any]:
    sport_counts: dict[str, int] = {}
    sport_duration_sec: dict[str, int] = {}
    session_types: dict[str, int] = {}
    intensity_distribution = {"easy": 0, "moderate": 0, "hard": 0, "unknown": 0}
    time_in_zones_sec: dict[str, int] = {}

    planned_by_id = {item.planned_session_id: item for item in context.planned_sessions}
    analyses_by_activity = {item.activity_id: item for item in context.session_analyses}

    for activity in context.activities:
        sport_key = activity.sport_type or "sin_deporte"
        sport_counts[sport_key] = sport_counts.get(sport_key, 0) + 1
        sport_duration_sec[sport_key] = sport_duration_sec.get(sport_key, 0) + (activity.duration_sec or 0)

        planned_session = planned_by_id.get(activity.matched_planned_session_id) if activity.matched_planned_session_id else None
        if planned_session and planned_session.session_type:
            session_type_key = planned_session.session_type
            session_types[session_type_key] = session_types.get(session_type_key, 0) + 1

        bucket = _classify_intensity_bucket(planned_session)
        intensity_distribution[bucket] = intensity_distribution.get(bucket, 0) + 1

        analysis = analyses_by_activity.get(activity.activity_id)
        if analysis is None:
            continue
        zone_map = (((analysis.metrics_json or {}).get("metrics") or {}).get("heart_rate") or {}).get("estimated_time_in_zones_sec")
        if isinstance(zone_map, dict):
            for zone_name, seconds in zone_map.items():
                try:
                    time_in_zones_sec[str(zone_name)] = time_in_zones_sec.get(str(zone_name), 0) + int(seconds)
                except (TypeError, ValueError):
                    continue

    intensity_zone_summary = _build_week_intensity_zone_summary(time_in_zones_sec)
    return {
        "sessions_by_sport": {
            "counts": sport_counts,
            "duration_sec": sport_duration_sec,
        },
        "session_types": session_types,
        "time_in_zones_sec": time_in_zones_sec,
        "intensity_zone_summary": intensity_zone_summary,
        "intensity_distribution": intensity_distribution,
    }


def _build_week_intensity_zone_summary(time_in_zones_sec: dict[str, int]) -> dict[str, Any]:
    total_time = sum(int(value) for value in time_in_zones_sec.values() if value)
    z1 = _zone_seconds(time_in_zones_sec, {"z1"})
    z2 = _zone_seconds(time_in_zones_sec, {"z2"})
    z3 = _zone_seconds(time_in_zones_sec, {"z3"})
    z4 = _zone_seconds(time_in_zones_sec, {"z4"})
    z5 = _zone_seconds(time_in_zones_sec, {"z5"})
    z4_plus = z4 + z5

    def pct(value: int) -> float | None:
        if total_time <= 0:
            return None
        return round((value / total_time) * 100.0, 1)

    return {
        "total_time_sec": total_time,
        "pct_z1": pct(z1),
        "pct_z2": pct(z2),
        "pct_z3": pct(z3),
        "pct_z4_plus": pct(z4_plus),
        "pct_z4": pct(z4),
    }


def _zone_seconds(time_in_zones_sec: dict[str, int], zone_names: set[str]) -> int:
    total = 0
    for zone_name, seconds in time_in_zones_sec.items():
        normalized = str(zone_name).strip().lower()
        if normalized in zone_names:
            total += int(seconds or 0)
    return total


def _build_week_compliance(context: WeeklyContext) -> dict[str, Any]:
    planned_sessions = len(context.planned_sessions)
    completed_sessions = sum(1 for item in context.planned_sessions if item.matched)
    compliance_ratio = None if planned_sessions == 0 else round(completed_sessions / planned_sessions, 3)
    compliance_ratio_pct = None if compliance_ratio is None else round(compliance_ratio * 100.0, 1)
    return {
        "planned_sessions": planned_sessions,
        "completed_sessions": completed_sessions,
        "compliance_ratio": compliance_ratio,
        "compliance_ratio_pct": compliance_ratio_pct,
    }


def _build_week_trends(context: WeeklyContext, totals: dict[str, Any]) -> dict[str, Any]:
    previous = context.previous_weeks
    avg_duration = _mean_known([item.total_duration_sec for item in previous])
    avg_distance = _mean_known([item.total_distance_m for item in previous])
    avg_elevation = _mean_known([item.total_elevation_gain_m for item in previous])
    avg_activities = _mean_known([item.activity_count for item in previous])

    return {
        "previous_weeks": [
            {
                "week_start_date": item.week_start_date.isoformat(),
                "week_end_date": item.week_end_date.isoformat(),
                "activity_count": item.activity_count,
                "total_duration_sec": item.total_duration_sec,
                "total_distance_m": item.total_distance_m,
                "total_elevation_gain_m": item.total_elevation_gain_m,
                "planned_sessions": item.planned_sessions,
                "completed_sessions": item.completed_sessions,
                "compliance_ratio": item.compliance_ratio,
            }
            for item in previous
        ],
        "duration_vs_prev_avg_pct": _delta_pct(avg_duration, totals["total_duration_sec"]),
        "distance_vs_prev_avg_pct": _delta_pct(avg_distance, totals["total_distance_m"]),
        "elevation_vs_prev_avg_pct": _delta_pct(avg_elevation, totals["total_elevation_gain_m"]),
        "activity_count_vs_prev_avg_pct": _delta_pct(avg_activities, totals["activity_count"]),
        "prev_avg_duration_sec": avg_duration,
        "prev_avg_distance_m": avg_distance,
        "prev_avg_elevation_gain_m": avg_elevation,
        "prev_avg_activity_count": avg_activities,
    }


def _build_week_consistency(context: WeeklyContext, totals: dict[str, Any]) -> dict[str, Any]:
    trained_days = len({item.activity_date for item in context.activities if item.activity_date is not None})
    rest_days = max(0, 7 - trained_days)
    active_day_ratio_pct = round((trained_days / 7.0) * 100.0, 1)
    peak_day_duration = max(totals["daily_duration_sec"].values(), default=0)
    peak_day_share_pct = None
    if totals["total_duration_sec"] > 0:
        peak_day_share_pct = round((peak_day_duration / totals["total_duration_sec"]) * 100.0, 1)
    distribution_label = "distribuida"
    if peak_day_share_pct is not None and peak_day_share_pct > POOR_DISTRIBUTION_PEAK_SHARE_PCT:
        distribution_label = "concentrada"
    elif trained_days <= 2:
        distribution_label = "escasa"

    return {
        "trained_days": trained_days,
        "rest_days": rest_days,
        "active_day_ratio_pct": active_day_ratio_pct,
        "peak_day_duration_sec": peak_day_duration,
        "peak_day_share_pct": peak_day_share_pct,
        "distribution_label": distribution_label,
    }


def _build_week_health_metrics(context: WeeklyContext) -> dict[str, Any]:
    return {
        "days_with_health": len(context.health_days),
        "avg_sleep_hours": _mean_known([item.sleep_hours for item in context.health_days]),
        "avg_sleep_score": _mean_known([item.sleep_score for item in context.health_days]),
        "avg_stress": _mean_known([item.stress_avg for item in context.health_days]),
        "avg_body_battery_end": _mean_known([item.body_battery_end for item in context.health_days]),
        "avg_hrv_ms": _mean_known([item.hrv_avg_ms for item in context.health_days]),
        "avg_recovery_time_hours": _mean_known([item.recovery_time_hours for item in context.health_days]),
        "avg_resting_hr": _mean_known([item.resting_hr for item in context.health_days]),
    }


def _build_session_analysis_aggregate(context: WeeklyContext) -> dict[str, Any]:
    return {
        "analysed_sessions": len(context.session_analyses),
        "avg_compliance_score": _mean_known([item.compliance_score for item in context.session_analyses]),
        "avg_execution_score": _mean_known([item.execution_score for item in context.session_analyses]),
        "avg_control_score": _mean_known([item.control_score for item in context.session_analyses]),
        "avg_fatigue_score": _mean_known([item.fatigue_score for item in context.session_analyses]),
    }


def _build_week_flags(
    context: WeeklyContext,
    totals: dict[str, Any],
    distribution: dict[str, Any],
    compliance: dict[str, Any],
    trends: dict[str, Any],
    consistency: dict[str, Any],
    health_context: dict[str, Any],
    session_aggregate: dict[str, Any],
) -> dict[str, Any]:
    duration_ratio = None
    if trends["prev_avg_duration_sec"] not in (None, 0):
        duration_ratio = totals["total_duration_sec"] / trends["prev_avg_duration_sec"]

    fatigue_proxy = average_scores(
        [
            session_aggregate["avg_fatigue_score"],
            _fatigue_load_component(totals["total_duration_sec"], trends["prev_avg_duration_sec"]),
            _health_fatigue_component(health_context),
        ]
    )
    provisional_consistency = average_scores(
        [
            _active_day_score(consistency["trained_days"]),
            _distribution_score(consistency["peak_day_share_pct"]),
            compliance["compliance_ratio_pct"],
        ]
    )

    intensity_imbalance_flag = _weekly_intensity_imbalance_flag(
        distribution.get("intensity_zone_summary", {})
    )

    return {
        "overload_flag": bool(duration_ratio is not None and duration_ratio > OVERLOAD_DURATION_RATIO),
        "undertraining_flag": bool(
            duration_ratio is not None
            and duration_ratio < UNDERTRAINING_DURATION_RATIO
            and (compliance["planned_sessions"] or 0) >= 3
        ),
        "poor_distribution_flag": bool(
            consistency["peak_day_share_pct"] is not None
            and consistency["peak_day_share_pct"] > POOR_DISTRIBUTION_PEAK_SHARE_PCT
        ),
        "high_fatigue_risk_flag": bool((fatigue_proxy or 0) >= HIGH_FATIGUE_SCORE_THRESHOLD),
        "low_consistency_flag": bool(
            provisional_consistency is not None and provisional_consistency < LOW_CONSISTENCY_SCORE_THRESHOLD
        ),
        "intensity_distribution_imbalance_flag": intensity_imbalance_flag,
    }


def _build_week_scores(
    context: WeeklyContext,
    totals: dict[str, Any],
    distribution: dict[str, Any],
    compliance: dict[str, Any],
    trends: dict[str, Any],
    consistency: dict[str, Any],
    health_context: dict[str, Any],
    session_aggregate: dict[str, Any],
) -> dict[str, Any]:
    duration_closeness = _closeness_to_recent_load(trends["duration_vs_prev_avg_pct"])
    distance_closeness = _closeness_to_recent_load(trends["distance_vs_prev_avg_pct"])
    load_score = average_scores([duration_closeness, distance_closeness, compliance["compliance_ratio_pct"]])

    consistency_score = average_scores(
        [
            _active_day_score(consistency["trained_days"]),
            _distribution_score(consistency["peak_day_share_pct"]),
            compliance["compliance_ratio_pct"],
        ]
    )

    hard_session_count = distribution["intensity_distribution"].get("hard", 0)
    fatigue_score = average_scores(
        [
            session_aggregate["avg_fatigue_score"],
            _fatigue_load_component(totals["total_duration_sec"], trends["prev_avg_duration_sec"]),
            clamp_score(hard_session_count * 25.0),
            _health_fatigue_component(health_context),
        ]
    )

    balance_score = average_scores(
        [
            _sport_balance_score(distribution["sessions_by_sport"].get("counts", {})),
            _intensity_balance_score(distribution["intensity_distribution"]),
        ]
    )

    weekly_intensity_balance_score = _weekly_intensity_balance_score(
        distribution.get("intensity_zone_summary", {})
    )

    return {
        "load_score": load_score,
        "consistency_score": consistency_score,
        "fatigue_score": fatigue_score,
        "balance_score": balance_score,
        "weekly_intensity_balance_score": weekly_intensity_balance_score,
    }


def _classify_intensity_bucket(planned_session: WeeklyPlannedSessionContext | None) -> str:
    if planned_session is None:
        return "unknown"
    zone_name = _session_intensity_zone(planned_session)
    if zone_name in {"Z1", "Z2"}:
        return "easy"
    if zone_name == "Z3":
        return "moderate"
    if zone_name in {"Z4", "Z5"}:
        return "hard"

    session_type = _normalized(planned_session.session_type)
    if session_type in {"recovery", "easy", "base", "long"}:
        return "easy"
    if session_type in {"tempo", "threshold", "steady"}:
        return "moderate"
    if session_type in {"hard", "race", "intervals", "vo2"}:
        return "hard"
    return "unknown"


def _session_intensity_zone(planned_session: WeeklyPlannedSessionContext) -> str | None:
    if planned_session.target_type == "hr":
        return planned_session.target_hr_zone
    if planned_session.target_type == "pace":
        return planned_session.target_pace_zone
    if planned_session.target_type == "power":
        return planned_session.target_power_zone
    if planned_session.target_type == "rpe":
        return planned_session.target_rpe_zone
    return None


def _closeness_to_recent_load(delta_pct: float | None) -> float | None:
    if delta_pct is None:
        return None
    return clamp_score(100.0 - abs(delta_pct))


def _active_day_score(trained_days: int) -> float:
    return clamp_score(min(100.0, (trained_days / 5.0) * 100.0)) or 0.0


def _distribution_score(peak_day_share_pct: float | None) -> float | None:
    if peak_day_share_pct is None:
        return None
    penalty = max(0.0, peak_day_share_pct - 25.0) * 3.0
    return clamp_score(100.0 - penalty)


def _fatigue_load_component(total_duration_sec: int | None, prev_avg_duration_sec: float | None) -> float | None:
    if total_duration_sec is None:
        return None
    if prev_avg_duration_sec and prev_avg_duration_sec > 0:
        delta_pct = ((total_duration_sec - prev_avg_duration_sec) / prev_avg_duration_sec) * 100.0
        if delta_pct <= 0:
            return clamp_score(45.0 + max(delta_pct, -40.0) * 0.3)
        return clamp_score(50.0 + delta_pct * 1.2)
    hours = total_duration_sec / 3600.0
    return clamp_score((hours / 10.0) * 100.0)


def _weekly_intensity_balance_score(intensity_summary: dict[str, Any]) -> float | None:
    if not intensity_summary:
        return None
    pct_z2 = intensity_summary.get("pct_z2")
    pct_z3 = intensity_summary.get("pct_z3")
    pct_z4_plus = intensity_summary.get("pct_z4_plus")
    pct_z4 = intensity_summary.get("pct_z4")
    if pct_z2 is None and pct_z3 is None and pct_z4_plus is None:
        return None
    score = 100.0
    if pct_z2 is not None and pct_z2 < 20:
        score -= 30.0
    if pct_z3 is not None and pct_z4_plus is not None and (pct_z3 + pct_z4_plus) > 60:
        score -= 35.0
    if pct_z4 is not None and pct_z4 > 25:
        score -= 25.0
    return clamp_score(score)


def _weekly_intensity_imbalance_flag(intensity_summary: dict[str, Any]) -> bool:
    if not intensity_summary:
        return False
    pct_z2 = intensity_summary.get("pct_z2")
    pct_z3 = intensity_summary.get("pct_z3")
    pct_z4_plus = intensity_summary.get("pct_z4_plus")
    pct_z4 = intensity_summary.get("pct_z4")
    if pct_z2 is not None and pct_z2 < 20:
        return True
    if pct_z3 is not None and pct_z4_plus is not None and (pct_z3 + pct_z4_plus) > 60:
        return True
    if pct_z4 is not None and pct_z4 > 25:
        return True
    return False


def _health_fatigue_component(health_context: dict[str, Any]) -> float | None:
    sleep_component = None
    stress_component = None
    body_battery_component = None
    if health_context["avg_sleep_hours"] is not None:
        sleep_component = clamp_score(100.0 - max(0.0, 7.5 - health_context["avg_sleep_hours"]) * 18.0)
    if health_context["avg_stress"] is not None:
        stress_component = clamp_score(float(health_context["avg_stress"]))
    if health_context["avg_body_battery_end"] is not None:
        body_battery_component = clamp_score(100.0 - float(health_context["avg_body_battery_end"]))
    return average_scores([sleep_component, stress_component, body_battery_component])


def _sport_balance_score(sport_counts: dict[str, int]) -> float | None:
    total = sum(sport_counts.values())
    if total == 0:
        return None
    if len(sport_counts) == 1:
        return 75.0
    dominant_share = max(sport_counts.values()) / total
    penalty = max(0.0, (dominant_share * 100.0) - 60.0) * 1.2
    return clamp_score(100.0 - penalty)


def _intensity_balance_score(intensity_distribution: dict[str, int]) -> float | None:
    total = sum(intensity_distribution.values())
    if total == 0:
        return None
    hard_share = (intensity_distribution.get("hard", 0) / total) * 100.0
    easy_share = (intensity_distribution.get("easy", 0) / total) * 100.0
    penalty = max(0.0, hard_share - 35.0) * 1.8 + max(0.0, 20.0 - easy_share) * 1.2
    return clamp_score(90.0 - penalty)


def _analysis_date(
    analysis: SessionAnalysis,
    activities: list[GarminActivity],
    planned_sessions: list[PlannedSession],
) -> date | None:
    activity_map = {item.id: item for item in activities}
    planned_map = {item.id: item for item in planned_sessions}
    if analysis.activity_id in activity_map:
        return _activity_local_date(activity_map[analysis.activity_id])
    planned = planned_map.get(analysis.planned_session_id)
    return planned.training_day.day_date if planned and planned.training_day else None


def _infer_primary_sport(athlete: Athlete) -> str | None:
    active_plan = next((plan for plan in athlete.training_plans if plan.status == "active" and plan.sport_type), None)
    if active_plan is not None:
        return active_plan.sport_type
    plan_with_sport = next((plan for plan in athlete.training_plans if plan.sport_type), None)
    return plan_with_sport.sport_type if plan_with_sport else None


def _activity_local_date(activity: GarminActivity) -> date | None:
    if activity.start_time is None:
        return None
    if activity.start_time.tzinfo is not None:
        return activity.start_time.astimezone().date()
    return activity.start_time.date()


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _coerce_date(value: date | str | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _weekly_thresholds() -> dict[str, float]:
    return {
        "overload_duration_ratio": OVERLOAD_DURATION_RATIO,
        "undertraining_duration_ratio": UNDERTRAINING_DURATION_RATIO,
        "poor_distribution_peak_share_pct": POOR_DISTRIBUTION_PEAK_SHARE_PCT,
        "low_consistency_score_threshold": LOW_CONSISTENCY_SCORE_THRESHOLD,
        "high_fatigue_score_threshold": HIGH_FATIGUE_SCORE_THRESHOLD,
        "intensity_min_z2_pct": 20.0,
        "intensity_max_z3_z4_pct": 60.0,
        "intensity_max_z4_pct": 25.0,
    }


def _mean_known(values: list[float | int | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(mean(usable), 2)


def _delta_pct(reference: float | int | None, actual: float | int | None) -> float | None:
    if reference in (None, 0) or actual is None:
        return None
    return round(((float(actual) - float(reference)) / float(reference)) * 100.0, 1)


def _normalized(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
