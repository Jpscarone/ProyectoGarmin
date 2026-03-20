from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.analysis_report import AnalysisReport
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession


@dataclass
class AnalysisBundleView:
    title: str
    bundle_data: dict[str, Any]
    json_text: str
    chatgpt_text: str


def build_bundle_for_session(db: Session, planned_session_id: int) -> AnalysisBundleView:
    planned_session = _get_session_bundle_source(db, planned_session_id)
    if planned_session is None:
        raise ValueError("Sesion planificada no encontrada.")

    activity = planned_session.activity_match.garmin_activity if planned_session.activity_match else None
    report = _latest_session_report(db, planned_session.id)
    health_metric = _health_for_session(db, planned_session)

    bundle = _assemble_bundle(
        planned_session=planned_session,
        activity=activity,
        health_metric=health_metric,
        report=report,
    )
    title = f"Bundle de sesion: {planned_session.name}"
    return _as_bundle_view(title, bundle)


def build_bundle_for_activity(db: Session, activity_id: int) -> AnalysisBundleView:
    activity = _get_activity_bundle_source(db, activity_id)
    if activity is None:
        raise ValueError("Actividad no encontrada.")

    planned_session = activity.activity_match.planned_session if activity.activity_match else None
    report = _latest_activity_report(db, activity.id)
    health_metric = _health_for_activity(db, activity, planned_session)

    bundle = _assemble_bundle(
        planned_session=planned_session,
        activity=activity,
        health_metric=health_metric,
        report=report,
    )
    title = f"Bundle de actividad: {activity.activity_name or activity.id}"
    return _as_bundle_view(title, bundle)


def build_bundle_for_report(db: Session, report_id: int) -> AnalysisBundleView:
    report = _get_report_bundle_source(db, report_id)
    if report is None:
        raise ValueError("Reporte no encontrado.")

    planned_session = report.planned_session
    activity = report.garmin_activity
    health_metric = None
    if planned_session is not None:
        health_metric = _health_for_session(db, planned_session)
    elif activity is not None:
        health_metric = _health_for_activity(db, activity, None)

    bundle = _assemble_bundle(
        planned_session=planned_session,
        activity=activity,
        health_metric=health_metric,
        report=report,
    )
    title = f"Bundle de reporte: {report.title}"
    return _as_bundle_view(title, bundle)


def _as_bundle_view(title: str, bundle: dict[str, Any]) -> AnalysisBundleView:
    json_text = json.dumps(bundle, ensure_ascii=True, indent=2, default=str)
    chatgpt_text = _build_chatgpt_summary(bundle)
    return AnalysisBundleView(title=title, bundle_data=bundle, json_text=json_text, chatgpt_text=chatgpt_text)


def _assemble_bundle(
    *,
    planned_session: PlannedSession | None,
    activity: GarminActivity | None,
    health_metric: DailyHealthMetric | None,
    report: AnalysisReport | None,
) -> dict[str, Any]:
    return {
        "planned_session": _serialize_planned_session(planned_session),
        "matched_activity": _serialize_activity(activity),
        "daily_health": _serialize_health(health_metric),
        "weather": _serialize_weather(activity.weather if activity else None),
        "automatic_analysis": _serialize_report(report),
    }


def _serialize_planned_session(planned_session: PlannedSession | None) -> dict[str, Any] | None:
    if planned_session is None:
        return None
    return {
        "date": str(planned_session.training_day.day_date) if planned_session.training_day else None,
        "sport_type": planned_session.sport_type,
        "discipline_variant": planned_session.discipline_variant,
        "name": planned_session.name,
        "description": planned_session.description_text,
        "session_type": planned_session.session_type,
        "expected_duration_min": planned_session.expected_duration_min,
        "expected_distance_km": planned_session.expected_distance_km,
        "expected_elevation_gain_m": planned_session.expected_elevation_gain_m,
        "target_hr_zone": planned_session.target_hr_zone,
        "target_power_zone": planned_session.target_power_zone,
        "target_notes": planned_session.target_notes,
        "steps": [
            {
                "step_order": step.step_order,
                "step_type": step.step_type,
                "repeat_count": step.repeat_count,
                "duration_sec": step.duration_sec,
                "distance_m": step.distance_m,
                "target_hr_min": step.target_hr_min,
                "target_hr_max": step.target_hr_max,
                "target_power_min": step.target_power_min,
                "target_power_max": step.target_power_max,
                "target_pace_min_sec_km": step.target_pace_min_sec_km,
                "target_pace_max_sec_km": step.target_pace_max_sec_km,
                "target_cadence_min": step.target_cadence_min,
                "target_cadence_max": step.target_cadence_max,
                "target_notes": step.target_notes,
            }
            for step in planned_session.planned_session_steps
        ],
    }


def _serialize_activity(activity: GarminActivity | None) -> dict[str, Any] | None:
    if activity is None:
        return None
    return {
        "id": activity.id,
        "garmin_activity_id": activity.garmin_activity_id,
        "name": activity.activity_name,
        "sport_type": activity.sport_type,
        "start_time": activity.start_time,
        "duration_sec": activity.duration_sec,
        "distance_m": activity.distance_m,
        "elevation_gain_m": activity.elevation_gain_m,
        "elevation_loss_m": activity.elevation_loss_m,
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "avg_power": activity.avg_power,
        "max_power": activity.max_power,
        "normalized_power": activity.normalized_power,
        "avg_speed_mps": activity.avg_speed_mps,
        "avg_pace_sec_km": activity.avg_pace_sec_km,
        "avg_cadence": activity.avg_cadence,
        "max_cadence": activity.max_cadence,
        "training_effect_aerobic": activity.training_effect_aerobic,
        "training_effect_anaerobic": activity.training_effect_anaerobic,
        "training_load": activity.training_load,
        "calories": activity.calories,
        "laps": [
            {
                "lap_number": lap.lap_number,
                "lap_type": lap.lap_type,
                "start_time": lap.start_time,
                "duration_sec": lap.duration_sec,
                "moving_duration_sec": lap.moving_duration_sec,
                "distance_m": lap.distance_m,
                "elevation_gain_m": lap.elevation_gain_m,
                "elevation_loss_m": lap.elevation_loss_m,
                "avg_hr": lap.avg_hr,
                "max_hr": lap.max_hr,
                "avg_power": lap.avg_power,
                "max_power": lap.max_power,
                "avg_speed_mps": lap.avg_speed_mps,
                "avg_pace_sec_km": lap.avg_pace_sec_km,
                "avg_cadence": lap.avg_cadence,
                "max_cadence": lap.max_cadence,
            }
            for lap in activity.laps
        ],
    }


def _serialize_health(metric: DailyHealthMetric | None) -> dict[str, Any] | None:
    if metric is None:
        return None
    return {
        "sleep_hours": metric.sleep_hours,
        "sleep_score": metric.sleep_score,
        "stress_avg": metric.stress_avg,
        "stress_max": metric.stress_max,
        "body_battery_start": metric.body_battery_start,
        "body_battery_end": metric.body_battery_end,
        "resting_hr": metric.resting_hr,
        "hrv_status": metric.hrv_status,
        "hrv_avg_ms": metric.hrv_avg_ms,
        "vo2max": metric.vo2max,
        "recovery_time_hours": metric.recovery_time_hours,
    }


def _serialize_weather(weather: Any) -> dict[str, Any] | None:
    if weather is None:
        return None
    return {
        "temperature_start_c": weather.temperature_start_c,
        "apparent_temperature_start_c": weather.apparent_temperature_start_c,
        "humidity_start_pct": weather.humidity_start_pct,
        "wind_speed_start_kmh": weather.wind_speed_start_kmh,
        "wind_direction_start_deg": weather.wind_direction_start_deg,
        "precipitation_start_mm": weather.precipitation_start_mm,
        "temperature_min_c": weather.temperature_min_c,
        "temperature_max_c": weather.temperature_max_c,
        "wind_speed_avg_kmh": weather.wind_speed_avg_kmh,
        "precipitation_total_mm": weather.precipitation_total_mm,
    }


def _serialize_report(report: AnalysisReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "overall_score": report.overall_score,
        "overall_status": report.overall_status,
        "summary_text": report.summary_text,
        "recommendation_text": report.recommendation_text,
        "final_conclusion_text": report.final_conclusion_text,
        "items": [
            {
                "item_order": item.item_order,
                "item_type": item.item_type,
                "reference_label": item.reference_label,
                "planned_value_text": item.planned_value_text,
                "actual_value_text": item.actual_value_text,
                "item_score": item.item_score,
                "item_status": item.item_status,
                "comment_text": item.comment_text,
            }
            for item in report.items
        ],
    }


def _build_chatgpt_summary(bundle: dict[str, Any]) -> str:
    sections: list[str] = [
        "Analiza esta sesion de entrenamiento con foco en cumplimiento, intensidad, contexto y conclusiones practicas.",
        "",
        "1. Sesion planificada",
        _format_mapping(bundle.get("planned_session")),
        "",
        "2. Actividad real vinculada",
        _format_mapping(bundle.get("matched_activity")),
        "",
        "3. Salud diaria",
        _format_mapping(bundle.get("daily_health")),
        "",
        "4. Clima",
        _format_mapping(bundle.get("weather")),
        "",
        "5. Analisis automatico actual",
        _format_mapping(bundle.get("automatic_analysis")),
        "",
        "Por favor devolve una conclusion breve, observaciones principales y si sugeris ajustar algo del plan.",
    ]
    return "\n".join(sections)


def _format_mapping(value: Any, indent: int = 0) -> str:
    if value is None:
        return "Sin datos."
    if isinstance(value, list):
        if not value:
            return "Sin datos."
        lines: list[str] = []
        prefix = " " * indent
        for index, item in enumerate(value, start=1):
            lines.append(f"{prefix}- item {index}")
            lines.append(_format_mapping(item, indent + 2))
        return "\n".join(lines)
    if isinstance(value, dict):
        if not value:
            return "Sin datos."
        lines: list[str] = []
        prefix = " " * indent
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_format_mapping(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {item}")
        return "\n".join(lines)
    return str(value)


def _get_session_bundle_source(db: Session, planned_session_id: int) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .where(PlannedSession.id == planned_session_id)
        .options(
            selectinload(PlannedSession.training_day),
            selectinload(PlannedSession.planned_session_steps),
            selectinload(PlannedSession.activity_match)
            .selectinload(ActivitySessionMatch.garmin_activity)
            .selectinload(GarminActivity.laps),
            selectinload(PlannedSession.activity_match)
            .selectinload(ActivitySessionMatch.garmin_activity)
            .selectinload(GarminActivity.weather),
        )
    )
    return db.scalar(statement)


def _get_activity_bundle_source(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.laps),
            selectinload(GarminActivity.weather),
            selectinload(GarminActivity.activity_match)
            .selectinload(ActivitySessionMatch.planned_session)
            .selectinload(PlannedSession.planned_session_steps),
            selectinload(GarminActivity.activity_match)
            .selectinload(ActivitySessionMatch.planned_session)
            .selectinload(PlannedSession.training_day),
        )
    )
    return db.scalar(statement)


def _get_report_bundle_source(db: Session, report_id: int) -> AnalysisReport | None:
    statement = (
        select(AnalysisReport)
        .where(AnalysisReport.id == report_id)
        .options(
            selectinload(AnalysisReport.items),
            selectinload(AnalysisReport.planned_session).selectinload(PlannedSession.planned_session_steps),
            selectinload(AnalysisReport.planned_session).selectinload(PlannedSession.training_day),
            selectinload(AnalysisReport.garmin_activity).selectinload(GarminActivity.laps),
            selectinload(AnalysisReport.garmin_activity).selectinload(GarminActivity.weather),
            selectinload(AnalysisReport.training_day),
        )
    )
    return db.scalar(statement)


def _latest_session_report(db: Session, planned_session_id: int) -> AnalysisReport | None:
    statement = (
        select(AnalysisReport)
        .where(AnalysisReport.planned_session_id == planned_session_id)
        .options(selectinload(AnalysisReport.items))
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    return db.scalar(statement)


def _latest_activity_report(db: Session, activity_id: int) -> AnalysisReport | None:
    statement = (
        select(AnalysisReport)
        .where(AnalysisReport.garmin_activity_id_fk == activity_id)
        .options(selectinload(AnalysisReport.items))
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    return db.scalar(statement)


def _health_for_session(db: Session, planned_session: PlannedSession) -> DailyHealthMetric | None:
    if planned_session.training_day is None:
        return None
    return _health_for_date(db, planned_session.athlete_id, planned_session.training_day.day_date)


def _health_for_activity(db: Session, activity: GarminActivity, planned_session: PlannedSession | None) -> DailyHealthMetric | None:
    if planned_session is not None and planned_session.training_day is not None:
        return _health_for_date(db, planned_session.athlete_id, planned_session.training_day.day_date)
    if activity.start_time is None:
        return None
    return _health_for_date(db, activity.athlete_id, activity.start_time.date())


def _health_for_date(db: Session, athlete_id: int, metric_date: date) -> DailyHealthMetric | None:
    statement = (
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date == metric_date,
        )
        .order_by(DailyHealthMetric.id.desc())
    )
    return db.scalar(statement)
