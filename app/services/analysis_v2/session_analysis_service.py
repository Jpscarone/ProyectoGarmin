from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.services.analysis_v2.metrics import compute_session_metrics
from app.services.analysis_v2.narrative import generate_session_narrative
from app.services.analysis_v2.schemas import NarrativeResult


ANALYSIS_VERSION = "v2"
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_WARNINGS = "completed_with_warnings"
STATUS_ERROR = "error"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AthleteProfileContext:
    id: int
    name: str | None
    primary_sport: str | None
    max_hr: int | None
    resting_hr: int | None
    lactate_threshold_hr: int | None
    running_threshold_pace_sec_km: int | None
    cycling_ftp: int | None
    vo2max: float | None
    hr_zones: dict[str, Any] | None
    pace_zones: dict[str, Any] | None
    power_zones: dict[str, Any] | None
    rpe_zones: dict[str, Any] | None


@dataclass(slots=True)
class PlannedStepContext:
    id: int
    order: int
    step_type: str
    repeat_count: int | None
    duration_sec: int | None
    distance_m: int | None
    target_type: str | None
    target_hr_zone: str | None
    target_hr_min: int | None
    target_hr_max: int | None
    target_power_zone: str | None
    target_power_min: int | None
    target_power_max: int | None
    target_pace_zone: str | None
    target_pace_min_sec_km: int | None
    target_pace_max_sec_km: int | None
    target_rpe_zone: str | None
    target_cadence_min: int | None
    target_cadence_max: int | None
    target_notes: str | None


@dataclass(slots=True)
class GoalContext:
    id: int
    name: str
    role: str | None
    sport_type: str | None
    event_date: date | None
    distance_km: float | None
    elevation_gain_m: float | None
    priority: str | None
    location_name: str | None


@dataclass(slots=True)
class PlannedSessionContext:
    id: int
    athlete_id: int
    training_day_id: int
    training_plan_id: int | None
    session_order: int
    session_date: date | None
    plan_name: str | None
    title: str
    sport_type: str | None
    discipline_variant: str | None
    session_type: str | None
    description: str | None
    target_notes: str | None
    planned_start_time: str | None
    expected_duration_min: int | None
    expected_distance_km: float | None
    expected_elevation_gain_m: float | None
    target_type: str | None
    target_hr_zone: str | None
    target_pace_zone: str | None
    target_power_zone: str | None
    target_rpe_zone: str | None
    is_key_session: bool
    day_type: str | None
    day_notes: str | None
    goal: GoalContext | None
    steps: list[PlannedStepContext] = field(default_factory=list)


@dataclass(slots=True)
class ActivityLapContext:
    index: int
    name: str | None
    lap_type: str | None
    start_time: str | None
    duration_sec: int | None
    moving_duration_sec: int | None
    distance_m: float | None
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    avg_hr: int | None
    max_hr: int | None
    avg_pace_sec_km: float | None
    avg_power: int | None
    max_power: int | None
    avg_cadence: float | None
    max_cadence: float | None


@dataclass(slots=True)
class WeatherContext:
    provider_name: str | None
    temperature_c: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    apparent_temperature_c: float | None
    humidity_pct: float | None
    wind_speed_kmh: float | None
    wind_direction_deg: float | None
    precipitation_mm: float | None
    precipitation_total_mm: float | None
    pressure_hpa: float | None
    condition_text: str | None


@dataclass(slots=True)
class HealthContext:
    metric_date: date
    sleep_hours: float | None
    sleep_score: int | None
    hrv_status: str | None
    hrv_avg_ms: float | None
    body_battery_start: int | None
    body_battery_end: int | None
    stress_avg: int | None
    recovery_time_hours: float | None
    resting_hr: int | None


@dataclass(slots=True)
class ActivityContext:
    id: int
    athlete_id: int
    garmin_activity_id: int
    title: str | None
    sport_type: str | None
    discipline_variant: str | None
    start_time: str | None
    end_time: str | None
    local_date: date | None
    duration_sec: int | None
    moving_duration_sec: int | None
    distance_m: float | None
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    avg_hr: int | None
    max_hr: int | None
    avg_power: int | None
    max_power: int | None
    normalized_power: int | None
    avg_speed_mps: float | None
    max_speed_mps: float | None
    avg_pace_sec_km: float | None
    avg_cadence: float | None
    max_cadence: float | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None
    training_load: float | None
    calories: float | None
    avg_temperature_c: float | None
    start_lat: float | None
    start_lon: float | None
    device_name: str | None


@dataclass(slots=True)
class RecentSimilarSessionContext:
    activity_id: int
    planned_session_id: int | None
    session_analysis_id: int | None
    date: date | None
    sport_type: str | None
    title: str | None
    duration_sec: int | None
    distance_m: float | None
    elevation_gain_m: float | None
    avg_hr: int | None
    avg_pace_sec_km: float | None
    analysis_summary: str | None


@dataclass(slots=True)
class WeeklySummaryContext:
    week_start: date
    week_end: date
    activity_count: int
    total_duration_sec: int
    total_distance_m: float
    total_elevation_gain_m: float
    activities_by_sport: dict[str, int]
    planned_session_count: int
    matched_session_count: int
    completed_ratio_pct: float | None


@dataclass(slots=True)
class SessionAnalysisContext:
    athlete: AthleteProfileContext
    planned_session: PlannedSessionContext
    activity: ActivityContext
    activity_laps: list[ActivityLapContext]
    weather: WeatherContext | None
    health: HealthContext | None
    recent_similar_sessions: list[RecentSimilarSessionContext]
    weekly_summary: WeeklySummaryContext

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_context(db: Session, planned_session_id: int, activity_id: int) -> SessionAnalysisContext:
    logger.info(
        "Building SessionAnalysisContext for planned_session_id=%s activity_id=%s",
        planned_session_id,
        activity_id,
    )

    planned_session = db.scalar(
        select(PlannedSession)
        .where(PlannedSession.id == planned_session_id)
        .options(
            selectinload(PlannedSession.athlete),
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            selectinload(PlannedSession.planned_session_steps),
        )
    )
    activity = db.scalar(
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.athlete),
            selectinload(GarminActivity.laps),
            selectinload(GarminActivity.weather),
        )
    )

    if planned_session is None:
        raise ValueError(f"No se encontro PlannedSession #{planned_session_id}.")
    if activity is None:
        raise ValueError(f"No se encontro GarminActivity #{activity_id}.")
    if planned_session.athlete is None:
        raise ValueError(f"La PlannedSession #{planned_session_id} no tiene athlete asociado.")

    activity_local_date = _activity_local_date(activity)
    context = SessionAnalysisContext(
        athlete=AthleteProfileContext(
            id=planned_session.athlete.id,
            name=planned_session.athlete.name,
            primary_sport=_infer_primary_sport(planned_session.athlete),
            max_hr=planned_session.athlete.max_hr,
            resting_hr=planned_session.athlete.resting_hr,
            lactate_threshold_hr=planned_session.athlete.lactate_threshold_hr,
            running_threshold_pace_sec_km=planned_session.athlete.running_threshold_pace_sec_km,
            cycling_ftp=planned_session.athlete.cycling_ftp,
            vo2max=planned_session.athlete.vo2max,
            hr_zones=_safe_json_loads(planned_session.athlete.hr_zones_json),
            pace_zones=_safe_json_loads(planned_session.athlete.pace_zones_json),
            power_zones=_safe_json_loads(planned_session.athlete.power_zones_json),
            rpe_zones=_safe_json_loads(planned_session.athlete.rpe_zones_json),
        ),
        planned_session=PlannedSessionContext(
            id=planned_session.id,
            athlete_id=planned_session.athlete_id,
            training_day_id=planned_session.training_day_id,
            training_plan_id=planned_session.training_day.training_plan.id if planned_session.training_day and planned_session.training_day.training_plan else None,
            session_order=planned_session.session_order,
            session_date=planned_session.training_day.day_date if planned_session.training_day else None,
            plan_name=planned_session.training_day.training_plan.name if planned_session.training_day and planned_session.training_day.training_plan else None,
            title=planned_session.name,
            sport_type=planned_session.sport_type,
            discipline_variant=planned_session.discipline_variant,
            session_type=planned_session.session_type,
            description=planned_session.description_text,
            target_notes=planned_session.target_notes,
            planned_start_time=planned_session.planned_start_time.isoformat() if planned_session.planned_start_time else None,
            expected_duration_min=planned_session.expected_duration_min,
            expected_distance_km=planned_session.expected_distance_km,
            expected_elevation_gain_m=planned_session.expected_elevation_gain_m,
            target_type=planned_session.target_type,
            target_hr_zone=planned_session.target_hr_zone,
            target_pace_zone=planned_session.target_pace_zone,
            target_power_zone=planned_session.target_power_zone,
            target_rpe_zone=planned_session.target_rpe_zone,
            is_key_session=planned_session.is_key_session,
            day_type=planned_session.training_day.day_type if planned_session.training_day else None,
            day_notes=planned_session.training_day.day_notes if planned_session.training_day else None,
            goal=_build_goal_context(planned_session),
            steps=[_build_planned_step_context(step) for step in planned_session.planned_session_steps],
        ),
        activity=ActivityContext(
            id=activity.id,
            athlete_id=activity.athlete_id,
            garmin_activity_id=activity.garmin_activity_id,
            title=activity.activity_name,
            sport_type=activity.sport_type,
            discipline_variant=activity.discipline_variant,
            start_time=activity.start_time.isoformat() if activity.start_time else None,
            end_time=activity.end_time.isoformat() if activity.end_time else None,
            local_date=activity_local_date,
            duration_sec=activity.duration_sec,
            moving_duration_sec=activity.moving_duration_sec,
            distance_m=activity.distance_m,
            elevation_gain_m=activity.elevation_gain_m,
            elevation_loss_m=activity.elevation_loss_m,
            avg_hr=activity.avg_hr,
            max_hr=activity.max_hr,
            avg_power=activity.avg_power,
            max_power=activity.max_power,
            normalized_power=activity.normalized_power,
            avg_speed_mps=activity.avg_speed_mps,
            max_speed_mps=activity.max_speed_mps,
            avg_pace_sec_km=activity.avg_pace_sec_km,
            avg_cadence=activity.avg_cadence,
            max_cadence=activity.max_cadence,
            training_effect_aerobic=activity.training_effect_aerobic,
            training_effect_anaerobic=activity.training_effect_anaerobic,
            training_load=activity.training_load,
            calories=activity.calories,
            avg_temperature_c=activity.avg_temperature_c,
            start_lat=activity.start_lat,
            start_lon=activity.start_lon,
            device_name=activity.device_name,
        ),
        activity_laps=[_build_activity_lap_context(lap) for lap in activity.laps],
        weather=_build_weather_context(activity),
        health=_build_health_context(db, planned_session.athlete.id, activity_local_date),
        recent_similar_sessions=_load_recent_similar_sessions(db, planned_session.athlete.id, activity),
        weekly_summary=_build_weekly_summary(db, planned_session.athlete.id, activity_local_date),
    )
    logger.info(
        "SessionAnalysisContext built: athlete_id=%s planned_steps=%s laps=%s recent_similar=%s",
        context.athlete.id,
        len(context.planned_session.steps),
        len(context.activity_laps),
        len(context.recent_similar_sessions),
    )
    return context


def compute_metrics(context: SessionAnalysisContext) -> dict[str, Any]:
    return compute_session_metrics(context)


def generate_narrative(context: SessionAnalysisContext, metrics: dict[str, Any]) -> NarrativeResult:
    return generate_session_narrative(context, metrics)


def run_session_analysis(
    db: Session,
    *,
    planned_session_id: int,
    activity_id: int,
    trigger_source: str = "auto",
) -> SessionAnalysis:
    logger.info(
        "Starting SessionAnalysis V2 pipeline planned_session_id=%s activity_id=%s trigger_source=%s",
        planned_session_id,
        activity_id,
        trigger_source,
    )

    analysis = _prepare_pending_analysis(
        db,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        trigger_source=trigger_source,
    )

    try:
        logger.info("SessionAnalysis V2 build_context started analysis_id=%s", analysis.id)
        context = build_context(db, planned_session_id, activity_id)
        logger.info("SessionAnalysis V2 build_context completed analysis_id=%s", analysis.id)
    except Exception as exc:
        logger.exception(
            "SessionAnalysis V2 build_context failed analysis_id=%s planned_session_id=%s activity_id=%s",
            analysis.id,
            planned_session_id,
            activity_id,
        )
        return _mark_analysis_error(
            db,
            analysis_id=analysis.id,
            error_message=f"build_context failed: {exc}",
        )

    try:
        logger.info("SessionAnalysis V2 compute_metrics started analysis_id=%s", analysis.id)
        metrics = compute_metrics(context)
        logger.info("SessionAnalysis V2 compute_metrics completed analysis_id=%s", analysis.id)
    except Exception as exc:
        logger.exception(
            "SessionAnalysis V2 compute_metrics failed analysis_id=%s planned_session_id=%s activity_id=%s",
            analysis.id,
            planned_session_id,
            activity_id,
        )
        return _mark_analysis_error(
            db,
            analysis_id=analysis.id,
            error_message=f"compute_metrics failed: {exc}",
        )

    metrics_payload = {
        "context": _to_jsonable(context.to_dict()),
        "metrics": _to_jsonable(metrics),
    }

    try:
        logger.info("SessionAnalysis V2 generate_narrative started analysis_id=%s", analysis.id)
        narrative = generate_narrative(context, metrics)
        logger.info(
            "SessionAnalysis V2 generate_narrative completed analysis_id=%s narrative_status=%s",
            analysis.id,
            narrative.narrative_status,
        )
    except Exception as exc:
        logger.exception(
            "SessionAnalysis V2 generate_narrative failed analysis_id=%s planned_session_id=%s activity_id=%s",
            analysis.id,
            planned_session_id,
            activity_id,
        )
        narrative = _fallback_narrative_from_exception(exc)

    final_status = STATUS_COMPLETED
    if narrative.narrative_status != "completed":
        final_status = STATUS_COMPLETED_WITH_WARNINGS

    refreshed = db.get(SessionAnalysis, analysis.id)
    if refreshed is None:
        raise ValueError(f"No se pudo rehidratar SessionAnalysis #{analysis.id}.")

    refreshed.status = final_status
    refreshed.trigger_source = trigger_source
    refreshed.analyzed_at = datetime.now(timezone.utc)
    refreshed.error_message = narrative.error_message
    refreshed.summary_short = narrative.summary_short
    refreshed.analysis_natural = narrative.analysis_natural
    refreshed.coach_conclusion = narrative.coach_conclusion
    refreshed.next_recommendation = narrative.next_recommendation
    refreshed.compliance_score = metrics["scores"]["compliance_score"]
    refreshed.execution_score = metrics["scores"]["execution_score"]
    refreshed.control_score = metrics["scores"]["control_score"]
    refreshed.fatigue_score = metrics["scores"]["fatigue_score"]
    refreshed.heat_impact_flag = metrics["derived_flags"]["heat_impact_flag"]
    refreshed.cardiac_drift_flag = metrics["derived_flags"]["cardiac_drift_flag"]
    refreshed.hydration_risk_flag = metrics["derived_flags"]["hydration_risk_flag"]
    refreshed.pace_instability_flag = metrics["derived_flags"]["pace_instability_flag"]
    refreshed.manual_review_needed = metrics["derived_flags"]["manual_review_needed"]
    refreshed.metrics_json = metrics_payload
    refreshed.llm_json = narrative.llm_json

    db.add(refreshed)
    db.commit()
    db.refresh(refreshed)
    logger.info(
        "SessionAnalysis V2 pipeline completed analysis_id=%s status=%s",
        refreshed.id,
        refreshed.status,
    )
    return refreshed


def re_run_session_analysis(
    db: Session,
    *,
    planned_session_id: int,
    activity_id: int,
    trigger_source: str = "manual_reanalysis",
) -> SessionAnalysis:
    logger.info(
        "Re-running SessionAnalysis V2 planned_session_id=%s activity_id=%s trigger_source=%s",
        planned_session_id,
        activity_id,
        trigger_source,
    )
    return run_session_analysis(
        db,
        planned_session_id=planned_session_id,
        activity_id=activity_id,
        trigger_source=trigger_source,
    )


def _build_goal_context(planned_session: PlannedSession) -> GoalContext | None:
    training_plan = planned_session.training_day.training_plan if planned_session.training_day else None
    if training_plan is None:
        return None

    goal = training_plan.goal
    if goal is None and training_plan.goals:
        goal = next((item for item in training_plan.goals if item.goal_role == "primary"), training_plan.goals[0])
    if goal is None:
        return None

    return GoalContext(
        id=goal.id,
        name=goal.name,
        role=goal.goal_role,
        sport_type=goal.sport_type,
        event_date=goal.event_date,
        distance_km=goal.distance_km,
        elevation_gain_m=goal.elevation_gain_m,
        priority=goal.priority,
        location_name=goal.location_name,
    )


def _prepare_pending_analysis(
    db: Session,
    *,
    planned_session_id: int,
    activity_id: int,
    trigger_source: str,
) -> SessionAnalysis:
    planned_session = db.get(PlannedSession, planned_session_id)
    activity = db.get(GarminActivity, activity_id)
    if planned_session is None:
        raise ValueError(f"No se encontro PlannedSession #{planned_session_id}.")
    if activity is None:
        raise ValueError(f"No se encontro GarminActivity #{activity_id}.")

    existing = list(
        db.scalars(
            select(SessionAnalysis)
            .where(
                SessionAnalysis.activity_id == activity_id,
                SessionAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .order_by(SessionAnalysis.id.desc())
        ).all()
    )

    analysis: SessionAnalysis
    if existing:
        analysis = existing[0]
        duplicates = existing[1:]
        for duplicate in duplicates:
            db.delete(duplicate)
    else:
        analysis = SessionAnalysis(
            athlete_id=planned_session.athlete_id,
            planned_session_id=planned_session_id,
            activity_id=activity_id,
            analysis_version=ANALYSIS_VERSION,
        )

    analysis.athlete_id = planned_session.athlete_id
    analysis.planned_session_id = planned_session_id
    analysis.activity_id = activity_id
    analysis.analysis_version = ANALYSIS_VERSION
    analysis.trigger_source = trigger_source
    analysis.status = STATUS_PENDING
    analysis.analyzed_at = None
    analysis.error_message = None
    analysis.summary_short = None
    analysis.analysis_natural = None
    analysis.coach_conclusion = None
    analysis.next_recommendation = None
    analysis.compliance_score = None
    analysis.execution_score = None
    analysis.control_score = None
    analysis.fatigue_score = None
    analysis.heat_impact_flag = None
    analysis.cardiac_drift_flag = None
    analysis.hydration_risk_flag = None
    analysis.pace_instability_flag = None
    analysis.manual_review_needed = None
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
    logger.info(
        "SessionAnalysis V2 pending record ready analysis_id=%s planned_session_id=%s activity_id=%s",
        analysis.id,
        planned_session_id,
        activity_id,
    )
    return analysis


def _mark_analysis_error(
    db: Session,
    *,
    analysis_id: int,
    error_message: str,
) -> SessionAnalysis:
    db.rollback()
    analysis = db.get(SessionAnalysis, analysis_id)
    if analysis is None:
        raise ValueError(f"No se pudo recuperar SessionAnalysis #{analysis_id} para marcar error.")

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
    logger.error("SessionAnalysis V2 marked as error analysis_id=%s error=%s", analysis.id, error_message)
    return analysis


def _fallback_narrative_from_exception(exc: Exception) -> NarrativeResult:
    return NarrativeResult(
        narrative_status="error",
        provider=None,
        model=None,
        summary_short="Analisis incompleto",
        analysis_natural=(
            "No se pudo generar la narrativa automatica, pero las metricas objetivas de la sesion si quedaron calculadas."
        ),
        coach_conclusion="La lectura narrativa queda pendiente por un fallo tecnico durante esta ejecucion.",
        next_recommendation="Reintentar el analisis cuando el servicio narrativo vuelva a estar disponible.",
        llm_json={
            "provider": None,
            "model": None,
            "status": STATUS_ERROR,
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        },
        error_message=str(exc),
    )


def _build_planned_step_context(step: Any) -> PlannedStepContext:
    return PlannedStepContext(
        id=step.id,
        order=step.step_order,
        step_type=step.step_type,
        repeat_count=step.repeat_count,
        duration_sec=step.duration_sec,
        distance_m=step.distance_m,
        target_type=step.target_type,
        target_hr_zone=step.target_hr_zone,
        target_hr_min=step.target_hr_min,
        target_hr_max=step.target_hr_max,
        target_power_zone=step.target_power_zone,
        target_power_min=step.target_power_min,
        target_power_max=step.target_power_max,
        target_pace_zone=step.target_pace_zone,
        target_pace_min_sec_km=step.target_pace_min_sec_km,
        target_pace_max_sec_km=step.target_pace_max_sec_km,
        target_rpe_zone=step.target_rpe_zone,
        target_cadence_min=step.target_cadence_min,
        target_cadence_max=step.target_cadence_max,
        target_notes=step.target_notes,
    )


def _build_activity_lap_context(lap: Any) -> ActivityLapContext:
    return ActivityLapContext(
        index=lap.lap_number,
        name=lap.lap_type,
        lap_type=lap.lap_type,
        start_time=lap.start_time.isoformat() if lap.start_time else None,
        duration_sec=lap.duration_sec,
        moving_duration_sec=lap.moving_duration_sec,
        distance_m=lap.distance_m,
        elevation_gain_m=lap.elevation_gain_m,
        elevation_loss_m=lap.elevation_loss_m,
        avg_hr=lap.avg_hr,
        max_hr=lap.max_hr,
        avg_pace_sec_km=lap.avg_pace_sec_km,
        avg_power=lap.avg_power,
        max_power=lap.max_power,
        avg_cadence=lap.avg_cadence,
        max_cadence=lap.max_cadence,
    )


def _build_weather_context(activity: GarminActivity) -> WeatherContext | None:
    weather = activity.weather
    if weather is None:
        return None

    condition_text = None
    raw_weather = _safe_json_loads(weather.raw_weather_json)
    if isinstance(raw_weather, dict):
        condition_text = raw_weather.get("condition") or raw_weather.get("weatherCode") or raw_weather.get("summary")

    return WeatherContext(
        provider_name=weather.provider_name,
        temperature_c=weather.temperature_start_c,
        temperature_min_c=weather.temperature_min_c,
        temperature_max_c=weather.temperature_max_c,
        apparent_temperature_c=weather.apparent_temperature_start_c,
        humidity_pct=weather.humidity_start_pct,
        wind_speed_kmh=weather.wind_speed_avg_kmh or weather.wind_speed_start_kmh,
        wind_direction_deg=weather.wind_direction_start_deg,
        precipitation_mm=weather.precipitation_start_mm,
        precipitation_total_mm=weather.precipitation_total_mm,
        pressure_hpa=weather.pressure_start_hpa,
        condition_text=condition_text,
    )


def _build_health_context(db: Session, athlete_id: int, activity_date: date | None) -> HealthContext | None:
    if activity_date is None:
        return None

    candidate_dates = [activity_date - timedelta(days=1), activity_date, activity_date + timedelta(days=1)]
    metrics = list(
        db.scalars(
            select(DailyHealthMetric)
            .where(
                DailyHealthMetric.athlete_id == athlete_id,
                DailyHealthMetric.metric_date.in_(candidate_dates),
            )
            .order_by(DailyHealthMetric.metric_date.desc())
        ).all()
    )
    if not metrics:
        return None

    metrics.sort(key=lambda item: (abs((item.metric_date - activity_date).days), item.metric_date != activity_date, -item.id))
    chosen = metrics[0]
    return HealthContext(
        metric_date=chosen.metric_date,
        sleep_hours=chosen.sleep_hours,
        sleep_score=chosen.sleep_score,
        hrv_status=chosen.hrv_status,
        hrv_avg_ms=chosen.hrv_avg_ms,
        body_battery_start=chosen.body_battery_start,
        body_battery_end=chosen.body_battery_end,
        stress_avg=chosen.stress_avg,
        recovery_time_hours=chosen.recovery_time_hours,
        resting_hr=chosen.resting_hr,
    )


def _load_recent_similar_sessions(db: Session, athlete_id: int, activity: GarminActivity) -> list[RecentSimilarSessionContext]:
    statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.id != activity.id,
            GarminActivity.start_time.is_not(None),
        )
        .options(selectinload(GarminActivity.activity_match))
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .limit(20)
    )
    activities = list(db.scalars(statement).all())
    current_sport = _normalized(activity.sport_type)

    def similarity_key(item: GarminActivity) -> tuple[int, float, float]:
        linked_priority = 0 if item.activity_match is not None else 1
        sport_priority = 0 if _normalized(item.sport_type) == current_sport else 1
        duration_diff = abs((item.duration_sec or 0) - (activity.duration_sec or 0))
        distance_diff = abs((item.distance_m or 0.0) - (activity.distance_m or 0.0))
        return (linked_priority, sport_priority, duration_diff, distance_diff)

    activities.sort(key=similarity_key)
    selected = activities[:5]
    if not selected:
        return []

    activity_ids = [item.id for item in selected]
    analyses = list(
        db.scalars(
            select(SessionAnalysis)
            .where(
                SessionAnalysis.activity_id.in_(activity_ids),
                SessionAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .order_by(SessionAnalysis.id.desc())
        ).all()
    )
    analysis_by_activity: dict[int, SessionAnalysis] = {}
    for analysis in analyses:
        analysis_by_activity.setdefault(analysis.activity_id, analysis)

    result: list[RecentSimilarSessionContext] = []
    for item in selected:
        match = item.activity_match
        analysis = analysis_by_activity.get(item.id)
        result.append(
            RecentSimilarSessionContext(
                activity_id=item.id,
                planned_session_id=match.planned_session_id_fk if match else None,
                session_analysis_id=analysis.id if analysis else None,
                date=_activity_local_date(item),
                sport_type=item.sport_type,
                title=item.activity_name,
                duration_sec=item.duration_sec,
                distance_m=item.distance_m,
                elevation_gain_m=item.elevation_gain_m,
                avg_hr=item.avg_hr,
                avg_pace_sec_km=item.avg_pace_sec_km,
                analysis_summary=analysis.summary_short if analysis else None,
            )
        )
    return result


def _build_weekly_summary(db: Session, athlete_id: int, activity_date: date | None) -> WeeklySummaryContext:
    if activity_date is None:
        activity_date = datetime.now().date()

    week_start = activity_date - timedelta(days=activity_date.weekday())
    week_end = week_start + timedelta(days=6)

    activity_statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
    )
    weekly_activities = [
        item
        for item in db.scalars(activity_statement).all()
        if _activity_local_date(item) is not None and week_start <= _activity_local_date(item) <= week_end
    ]

    sport_counts: dict[str, int] = {}
    total_duration_sec = 0
    total_distance_m = 0.0
    total_elevation_gain_m = 0.0
    for item in weekly_activities:
        sport_key = item.sport_type or "sin_deporte"
        sport_counts[sport_key] = sport_counts.get(sport_key, 0) + 1
        total_duration_sec += item.duration_sec or 0
        total_distance_m += item.distance_m or 0.0
        total_elevation_gain_m += item.elevation_gain_m or 0.0

    planned_statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= week_start,
            TrainingDay.day_date <= week_end,
        )
        .options(selectinload(PlannedSession.activity_match))
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc())
    )
    planned_sessions = list(db.scalars(planned_statement).all())
    matched_session_count = sum(1 for item in planned_sessions if item.activity_match is not None)
    completed_ratio_pct = None
    if planned_sessions:
        completed_ratio_pct = round((matched_session_count / len(planned_sessions)) * 100.0, 1)

    return WeeklySummaryContext(
        week_start=week_start,
        week_end=week_end,
        activity_count=len(weekly_activities),
        total_duration_sec=total_duration_sec,
        total_distance_m=round(total_distance_m, 2),
        total_elevation_gain_m=round(total_elevation_gain_m, 2),
        activities_by_sport=sport_counts,
        planned_session_count=len(planned_sessions),
        matched_session_count=matched_session_count,
        completed_ratio_pct=completed_ratio_pct,
    )


def _infer_primary_sport(athlete: Any) -> str | None:
    plans = list(getattr(athlete, "training_plans", []) or [])
    if not plans:
        return None
    active_plan = next((plan for plan in plans if plan.status == "active" and plan.sport_type), None)
    if active_plan is not None:
        return active_plan.sport_type
    with_sport = next((plan for plan in plans if plan.sport_type), None)
    return with_sport.sport_type if with_sport else None


def _safe_json_loads(raw_value: str | None) -> dict[str, Any] | None:
    if not raw_value:
        return None
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("No se pudo parsear JSON en SessionAnalysisContext.", exc_info=True)
        return None
    return value if isinstance(value, dict) else {"value": value}


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


def _activity_local_date(activity: GarminActivity) -> date | None:
    if activity.start_time is None:
        return None
    if activity.start_time.tzinfo is not None:
        return activity.start_time.astimezone().date()
    return activity.start_time.date()


def _normalized(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_")
