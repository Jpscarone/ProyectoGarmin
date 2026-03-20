from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.db.models.activity_weather import ActivityWeather
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.services.analysis.scoring import (
    aggregate_scores,
    compare_range,
    compare_relative,
    item_status_from_score,
    overall_status_from_score,
)


@dataclass
class AnalysisComparison:
    title: str
    overall_score: float | None
    overall_status: str
    summary_facts: list[str]
    context_notes: list[str]
    item_rows: list[dict[str, Any]]
    analysis_context: dict[str, Any]


def compare_planned_session_to_activity(
    planned_session: PlannedSession,
    activity: GarminActivity | None,
    health_metric: DailyHealthMetric | None,
    weather: ActivityWeather | None,
) -> AnalysisComparison:
    title = f"Analisis de sesion: {planned_session.name}"
    if activity is None:
        context_notes = _build_context_notes(health_metric, weather)
        return AnalysisComparison(
            title=title,
            overall_score=None,
            overall_status="review",
            summary_facts=["No hay actividad Garmin vinculada para comparar esta sesion."],
            context_notes=context_notes,
            item_rows=[
                {
                    "item_order": 1,
                    "item_type": "note",
                    "reference_label": "Sin actividad",
                    "planned_value_text": planned_session.name,
                    "actual_value_text": "Sin actividad vinculada",
                    "item_score": None,
                    "item_status": "review",
                    "comment_text": "No se puede evaluar la sesion sin una actividad vinculada.",
                }
            ],
            analysis_context=_build_context_payload(planned_session, activity, health_metric, weather),
        )

    context_notes = _build_context_notes(health_metric, weather)
    global_rows, summary_facts, intensity_context_notes = _build_global_rows(
        planned_session,
        activity,
        health_metric,
        weather,
    )
    if intensity_context_notes:
        context_notes.extend(intensity_context_notes)
    item_rows = _build_item_rows(planned_session, activity)

    overall_score = aggregate_scores(
        [row["item_score"] for row in global_rows],
        [row["item_score"] for row in item_rows],
    )
    force_review = _needs_review(planned_session, activity, global_rows + item_rows)
    overall_status = overall_status_from_score(overall_score, force_review=force_review)

    return AnalysisComparison(
        title=title,
        overall_score=overall_score,
        overall_status=overall_status,
        summary_facts=summary_facts,
        context_notes=context_notes,
        item_rows=global_rows + item_rows,
        analysis_context=_build_context_payload(planned_session, activity, health_metric, weather),
    )


def _build_global_rows(
    planned_session: PlannedSession,
    activity: GarminActivity,
    health_metric: DailyHealthMetric | None,
    weather: ActivityWeather | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    facts: list[str] = []
    context_notes: list[str] = []
    order = 1

    sport_ok = _normalize_sport(planned_session.sport_type) == _normalize_sport(activity.sport_type)
    sport_score = 100.0 if sport_ok else 0.0
    rows.append(
        {
            "item_order": order,
            "item_type": "segment",
            "reference_label": "Deporte",
            "planned_value_text": planned_session.sport_type or "-",
            "actual_value_text": activity.sport_type or "-",
            "item_score": sport_score,
            "item_status": item_status_from_score(sport_score),
            "comment_text": "Deporte coincidente." if sport_ok else "El deporte real no coincide con la sesion planificada.",
        }
    )
    facts.append("deporte correcto" if sport_ok else "deporte distinto al plan")
    order += 1

    if planned_session.expected_duration_min:
        duration_result = compare_relative(
            planned_session.expected_duration_min,
            (activity.duration_sec or 0) / 60.0 if activity.duration_sec else None,
        )
        rows.append(
            {
                "item_order": order,
                "item_type": "segment",
                "reference_label": "Duracion global",
                "planned_value_text": f"{planned_session.expected_duration_min} min",
                "actual_value_text": f"{round((activity.duration_sec or 0) / 60.0, 1)} min" if activity.duration_sec else "-",
                "item_score": duration_result["score"],
                "item_status": item_status_from_score(duration_result["score"], force_review=duration_result["status"] == "review"),
                "comment_text": _generic_metric_comment("duracion", duration_result),
            }
        )
        facts.append(_status_fact("duracion", duration_result["status"]))
        order += 1

    if planned_session.expected_distance_km:
        distance_result = compare_relative(
            planned_session.expected_distance_km,
            (activity.distance_m or 0) / 1000.0 if activity.distance_m else None,
        )
        rows.append(
            {
                "item_order": order,
                "item_type": "segment",
                "reference_label": "Distancia global",
                "planned_value_text": f"{planned_session.expected_distance_km} km",
                "actual_value_text": f"{round((activity.distance_m or 0) / 1000.0, 2)} km" if activity.distance_m else "-",
                "item_score": distance_result["score"],
                "item_status": item_status_from_score(distance_result["score"], force_review=distance_result["status"] == "review"),
                "comment_text": _generic_metric_comment("distancia", distance_result),
            }
        )
        facts.append(_status_fact("distancia", distance_result["status"]))
        order += 1

    if planned_session.expected_elevation_gain_m:
        elev_result = compare_relative(planned_session.expected_elevation_gain_m, activity.elevation_gain_m)
        rows.append(
            {
                "item_order": order,
                "item_type": "segment",
                "reference_label": "Elevacion",
                "planned_value_text": f"{planned_session.expected_elevation_gain_m} m+",
                "actual_value_text": f"{round(activity.elevation_gain_m, 1)} m+" if activity.elevation_gain_m is not None else "-",
                "item_score": elev_result["score"],
                "item_status": item_status_from_score(elev_result["score"], force_review=elev_result["status"] == "review"),
                "comment_text": _generic_metric_comment("elevacion", elev_result),
            }
        )
        facts.append(_status_fact("elevacion", elev_result["status"]))

    if not planned_session.planned_session_steps:
        intensity_row, intensity_fact, intensity_notes = _build_simple_intensity_row(
            planned_session,
            activity,
            health_metric,
            weather,
            item_order=order + 1,
        )
        if intensity_row is not None:
            rows.append(intensity_row)
            facts.append(intensity_fact)
        context_notes.extend(intensity_notes)

    return rows, facts, context_notes


def _build_item_rows(planned_session: PlannedSession, activity: GarminActivity) -> list[dict[str, Any]]:
    steps = list(planned_session.planned_session_steps)
    laps = list(activity.laps)

    if steps and laps:
        return _compare_steps_to_laps(steps, laps, offset=100)

    if steps and not laps:
        return [
            {
                "item_order": 100 + index,
                "item_type": step.step_type,
                "reference_label": f"Step {step.step_order}",
                "planned_value_text": _planned_step_text(step),
                "actual_value_text": "Sin laps disponibles",
                "item_score": None,
                "item_status": "review",
                "comment_text": "La sesion tiene steps, pero la actividad no tiene laps suficientes para compararlos.",
            }
            for index, step in enumerate(steps, start=1)
        ]

    if not steps:
        score = aggregate_scores(
            [],
            [
                compare_relative(planned_session.expected_duration_min, (activity.duration_sec or 0) / 60.0 if activity.duration_sec and planned_session.expected_duration_min else None)["score"],
                compare_relative(planned_session.expected_distance_km, (activity.distance_m or 0) / 1000.0 if activity.distance_m and planned_session.expected_distance_km else None)["score"],
            ],
        )
        return [
            {
                "item_order": 100,
                "item_type": "segment",
                "reference_label": "Sesion continua",
                "planned_value_text": _session_expectation_text(planned_session),
                "actual_value_text": _activity_actual_text(activity),
                "item_score": score,
                "item_status": item_status_from_score(score, force_review=score is None),
                "comment_text": "Sesion simple comparada a nivel global.",
            }
        ]

    return [
        {
            "item_order": 100,
            "item_type": "lap",
            "reference_label": "Actividad sin steps",
            "planned_value_text": _session_expectation_text(planned_session),
            "actual_value_text": _activity_actual_text(activity),
            "item_score": None,
            "item_status": "review",
            "comment_text": "No hubo estructura suficiente para un analisis por bloques.",
        }
    ]


def _compare_steps_to_laps(steps: list[PlannedSessionStep], laps: list[GarminActivityLap], *, offset: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    max_len = max(len(steps), len(laps))
    for index in range(max_len):
        step = steps[index] if index < len(steps) else None
        lap = laps[index] if index < len(laps) else None

        if step and lap:
            metric_scores: list[float | None] = []
            duration_result = compare_relative(step.duration_sec, lap.duration_sec)
            distance_result = compare_relative(step.distance_m, lap.distance_m)
            hr_result = compare_range(step.target_hr_min, step.target_hr_max, lap.avg_hr)
            power_result = compare_range(step.target_power_min, step.target_power_max, lap.avg_power)
            pace_result = compare_range(step.target_pace_min_sec_km, step.target_pace_max_sec_km, lap.avg_pace_sec_km)
            cadence_result = compare_range(step.target_cadence_min, step.target_cadence_max, lap.avg_cadence)
            metric_scores.extend([
                duration_result["score"],
                distance_result["score"],
                hr_result["score"],
                power_result["score"],
                pace_result["score"],
                cadence_result["score"],
            ])
            item_score = aggregate_scores([], metric_scores)
            rows.append(
                {
                    "item_order": offset + index + 1,
                    "item_type": step.step_type,
                    "reference_label": f"Step {step.step_order} / Lap {lap.lap_number}",
                    "planned_value_text": _planned_step_text(step),
                    "actual_value_text": _actual_lap_text(lap),
                    "item_score": item_score,
                    "item_status": item_status_from_score(item_score, force_review=item_score is None),
                    "comment_text": _step_comment(step, duration_result, distance_result, hr_result, power_result, pace_result, cadence_result),
                }
            )
        elif step and not lap:
            rows.append(
                {
                    "item_order": offset + index + 1,
                    "item_type": step.step_type,
                    "reference_label": f"Step {step.step_order}",
                    "planned_value_text": _planned_step_text(step),
                    "actual_value_text": "Sin lap correspondiente",
                    "item_score": None,
                    "item_status": "skipped",
                    "comment_text": "El bloque planificado no tuvo un lap correspondiente en la actividad.",
                }
            )
        elif lap and not step:
            rows.append(
                {
                    "item_order": offset + index + 1,
                    "item_type": "lap",
                    "reference_label": f"Lap {lap.lap_number}",
                    "planned_value_text": "Sin step planificado",
                    "actual_value_text": _actual_lap_text(lap),
                    "item_score": None,
                    "item_status": "review",
                    "comment_text": "La actividad tuvo un lap extra sin step equivalente en el plan.",
                }
            )
    return rows


def _build_context_notes(health_metric: DailyHealthMetric | None, weather: ActivityWeather | None) -> list[str]:
    notes: list[str] = []
    if health_metric is not None:
        if health_metric.sleep_hours is not None and health_metric.sleep_hours < 6:
            notes.append("Sueno bajo el dia del entrenamiento.")
        if health_metric.stress_avg is not None and health_metric.stress_avg >= 40:
            notes.append("Stress diario relativamente alto.")
        if health_metric.body_battery_start is not None and health_metric.body_battery_start < 40:
            notes.append("Body Battery bajo al inicio del dia.")
    if weather is not None:
        if weather.temperature_start_c is not None and weather.temperature_start_c >= 28:
            notes.append("Temperatura alta al inicio de la actividad.")
        if weather.wind_speed_start_kmh is not None and weather.wind_speed_start_kmh >= 25:
            notes.append("Viento fuerte al inicio de la actividad.")
        if weather.precipitation_total_mm is not None and weather.precipitation_total_mm > 1:
            notes.append("Hubo precipitacion durante la ventana de la actividad.")
    return notes


def _build_simple_intensity_row(
    planned_session: PlannedSession,
    activity: GarminActivity,
    health_metric: DailyHealthMetric | None,
    weather: ActivityWeather | None,
    *,
    item_order: int,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    intensity_plan = _resolve_intensity_plan(planned_session, activity)
    if intensity_plan is None:
        return (
            {
                "item_order": item_order,
                "item_type": "steady",
                "reference_label": "Intensidad global",
                "planned_value_text": planned_session.target_hr_zone or planned_session.target_power_zone or planned_session.target_notes or "Sin objetivo claro",
                "actual_value_text": "Sin datos suficientes",
                "item_score": None,
                "item_status": "review",
                "comment_text": "No hay datos suficientes para validar intensidad.",
            },
            "intensidad con datos insuficientes",
            [],
        )

    range_result = compare_range(
        intensity_plan["minimum"],
        intensity_plan["maximum"],
        intensity_plan["actual"],
        partial_tolerance=intensity_plan["partial_tolerance"],
    )
    status = item_status_from_score(range_result["score"], force_review=range_result["status"] == "review")
    direction = range_result.get("direction")
    comment = _intensity_comment(intensity_plan["metric_label"], status, direction)
    context_notes = _intensity_context_notes(intensity_plan, status, direction, health_metric, weather)

    row = {
        "item_order": item_order,
        "item_type": "steady",
        "reference_label": f"Intensidad global ({intensity_plan['metric_label']})",
        "planned_value_text": intensity_plan["planned_text"],
        "actual_value_text": intensity_plan["actual_text"],
        "item_score": range_result["score"],
        "item_status": status,
        "comment_text": comment,
    }
    fact = _intensity_fact(status, direction)
    return row, fact, context_notes


def _resolve_intensity_plan(planned_session: PlannedSession, activity: GarminActivity) -> dict[str, Any] | None:
    athlete = planned_session.athlete
    notes_level = _infer_intensity_level(planned_session.target_notes)

    actual_power = activity.normalized_power or activity.avg_power
    if actual_power is not None:
        if planned_session.target_power_zone:
            power_range = _resolve_power_range(athlete.cycling_ftp, planned_session.target_power_zone)
            if power_range is not None:
                minimum, maximum = power_range
                return {
                    "metric_key": "power",
                    "metric_label": "power",
                    "minimum": minimum,
                    "maximum": maximum,
                    "actual": float(actual_power),
                    "partial_tolerance": 5.0,
                    "planned_text": f"Power zone {planned_session.target_power_zone} ({round(minimum)}-{round(maximum)})",
                    "actual_text": f"{round(actual_power)} W",
                }
        if notes_level and athlete.cycling_ftp:
            power_range = _range_from_intensity_level(notes_level, athlete.cycling_ftp, metric="power")
            if power_range is not None:
                minimum, maximum = power_range
                return {
                    "metric_key": "power",
                    "metric_label": "power",
                    "minimum": minimum,
                    "maximum": maximum,
                    "actual": float(actual_power),
                    "partial_tolerance": 5.0,
                    "planned_text": f"Objetivo {notes_level} ({round(minimum)}-{round(maximum)} W)",
                    "actual_text": f"{round(actual_power)} W",
                }

    if activity.avg_hr is not None:
        if planned_session.target_hr_zone:
            hr_range = _resolve_hr_range(athlete.max_hr, planned_session.target_hr_zone)
            if hr_range is not None:
                minimum, maximum = hr_range
                return {
                    "metric_key": "hr",
                    "metric_label": "FC",
                    "minimum": minimum,
                    "maximum": maximum,
                    "actual": float(activity.avg_hr),
                    "partial_tolerance": 5.0,
                    "planned_text": f"HR zone {planned_session.target_hr_zone} ({round(minimum)}-{round(maximum)} bpm)",
                    "actual_text": f"{activity.avg_hr} bpm",
                }
        if notes_level and athlete.max_hr:
            hr_range = _range_from_intensity_level(notes_level, athlete.max_hr, metric="hr")
            if hr_range is not None:
                minimum, maximum = hr_range
                return {
                    "metric_key": "hr",
                    "metric_label": "FC",
                    "minimum": minimum,
                    "maximum": maximum,
                    "actual": float(activity.avg_hr),
                    "partial_tolerance": 5.0,
                    "planned_text": f"Objetivo {notes_level} ({round(minimum)}-{round(maximum)} bpm)",
                    "actual_text": f"{activity.avg_hr} bpm",
                }

    actual_pace = activity.avg_pace_sec_km or (1000.0 / activity.avg_speed_mps if activity.avg_speed_mps else None)
    if actual_pace is not None and notes_level and athlete.running_threshold_pace_sec_km:
        pace_range = _range_from_intensity_level(notes_level, athlete.running_threshold_pace_sec_km, metric="pace")
        if pace_range is not None:
            minimum, maximum = pace_range
            return {
                "metric_key": "pace",
                "metric_label": "pace",
                "minimum": minimum,
                "maximum": maximum,
                "actual": float(actual_pace),
                "partial_tolerance": 15.0,
                "planned_text": f"Objetivo {notes_level} ({round(minimum)}-{round(maximum)} s/km)",
                "actual_text": f"{round(actual_pace, 1)} s/km",
            }

    return None


def _needs_review(planned_session: PlannedSession, activity: GarminActivity, rows: list[dict[str, Any]]) -> bool:
    if not activity.laps and planned_session.planned_session_steps:
        return True
    if (
        (planned_session.target_hr_zone or planned_session.target_power_zone or planned_session.target_notes)
        and any(str(item.get("reference_label", "")).startswith("Intensidad global") and item["item_status"] == "review" for item in rows)
    ):
        return True
    review_or_skipped = sum(1 for item in rows if item["item_status"] in {"review", "skipped"})
    return bool(rows) and review_or_skipped >= max(2, len(rows) // 2 + 1)


def _build_context_payload(
    planned_session: PlannedSession,
    activity: GarminActivity | None,
    health_metric: DailyHealthMetric | None,
    weather: ActivityWeather | None,
) -> dict[str, Any]:
    return {
        "planned_session_id": planned_session.id,
        "garmin_activity_id": activity.id if activity else None,
        "has_steps": bool(planned_session.planned_session_steps),
        "lap_count": len(activity.laps) if activity else 0,
        "health_metric_id": health_metric.id if health_metric else None,
        "weather_id": weather.id if weather else None,
    }


def _status_fact(label: str, status: str | None) -> str:
    mapping = {
        "correct": f"{label} correcta",
        "partial": f"{label} parcial",
        "failed": f"{label} por debajo de lo esperado",
        "review": f"{label} con datos insuficientes",
    }
    return mapping.get(status or "review", f"{label} con revision pendiente")


def _generic_metric_comment(label: str, result: dict[str, Any]) -> str:
    status = result["status"]
    if status == "correct":
        return f"{label.capitalize()} correcta."
    if status == "partial":
        return f"{label.capitalize()} cerca del objetivo."
    if status == "failed":
        return f"{label.capitalize()} fuera del margen esperado."
    return f"No hubo datos suficientes para evaluar la {label}."


def _step_comment(
    step: PlannedSessionStep,
    duration_result: dict[str, Any],
    distance_result: dict[str, Any],
    hr_result: dict[str, Any],
    power_result: dict[str, Any],
    pace_result: dict[str, Any],
    cadence_result: dict[str, Any],
) -> str:
    comments: list[str] = []
    if step.duration_sec and duration_result["status"] == "failed":
        comments.append("duracion fuera del margen")
    if step.distance_m and distance_result["status"] == "failed":
        comments.append("distancia distinta a la planificada")
    if (step.target_hr_min or step.target_hr_max) and hr_result["status"] == "failed":
        comments.append("FC fuera del rango")
    if (step.target_power_min or step.target_power_max) and power_result["status"] == "failed":
        comments.append("potencia fuera del rango")
    if (step.target_pace_min_sec_km or step.target_pace_max_sec_km) and pace_result["status"] == "failed":
        comments.append("ritmo fuera del objetivo")
    if (step.target_cadence_min or step.target_cadence_max) and cadence_result["status"] == "failed":
        comments.append("cadencia fuera del objetivo")
    if not comments:
        return f"{step.step_type.capitalize()} evaluado correctamente o con desviaciones menores."
    return "; ".join(comments).capitalize() + "."


def _planned_step_text(step: PlannedSessionStep) -> str:
    parts: list[str] = []
    if step.duration_sec:
        parts.append(f"{step.duration_sec}s")
    if step.distance_m:
        parts.append(f"{step.distance_m}m")
    if step.repeat_count:
        parts.append(f"x{step.repeat_count}")
    if step.target_hr_min or step.target_hr_max:
        parts.append(f"HR {step.target_hr_min or '-'}-{step.target_hr_max or '-'}")
    if step.target_power_min or step.target_power_max:
        parts.append(f"Power {step.target_power_min or '-'}-{step.target_power_max or '-'}")
    if step.target_pace_min_sec_km or step.target_pace_max_sec_km:
        parts.append(f"Pace {step.target_pace_min_sec_km or '-'}-{step.target_pace_max_sec_km or '-'}")
    if step.target_cadence_min or step.target_cadence_max:
        parts.append(f"Cadence {step.target_cadence_min or '-'}-{step.target_cadence_max or '-'}")
    return " | ".join(parts) or "Sin objetivos cuantificables"


def _actual_lap_text(lap: GarminActivityLap) -> str:
    parts: list[str] = []
    if lap.duration_sec:
        parts.append(f"{lap.duration_sec}s")
    if lap.distance_m:
        parts.append(f"{round(lap.distance_m, 1)}m")
    if lap.avg_hr:
        parts.append(f"avgHR {lap.avg_hr}")
    if lap.avg_power:
        parts.append(f"avgPower {lap.avg_power}")
    if lap.avg_pace_sec_km:
        parts.append(f"pace {round(lap.avg_pace_sec_km, 1)}")
    if lap.avg_cadence:
        parts.append(f"cad {round(lap.avg_cadence, 1)}")
    return " | ".join(parts) or "Lap sin metricas relevantes"


def _session_expectation_text(planned_session: PlannedSession) -> str:
    parts: list[str] = []
    if planned_session.expected_duration_min:
        parts.append(f"{planned_session.expected_duration_min} min")
    if planned_session.expected_distance_km:
        parts.append(f"{planned_session.expected_distance_km} km")
    if planned_session.target_hr_zone:
        parts.append(f"HR zone {planned_session.target_hr_zone}")
    if planned_session.target_power_zone:
        parts.append(f"Power zone {planned_session.target_power_zone}")
    return " | ".join(parts) or planned_session.name


def _activity_actual_text(activity: GarminActivity) -> str:
    parts: list[str] = []
    if activity.duration_sec:
        parts.append(f"{round(activity.duration_sec / 60.0, 1)} min")
    if activity.distance_m:
        parts.append(f"{round(activity.distance_m / 1000.0, 2)} km")
    if activity.avg_hr:
        parts.append(f"avgHR {activity.avg_hr}")
    if activity.avg_power:
        parts.append(f"avgPower {activity.avg_power}")
    return " | ".join(parts) or activity.activity_name or "Sin metricas globales"


def _intensity_comment(metric_label: str, status: str, direction: str | None) -> str:
    if status == "correct":
        return f"Intensidad correcta en {metric_label}."
    if status == "partial":
        if direction == "above":
            return f"Intensidad ligeramente superior al objetivo en {metric_label}."
        if direction == "below":
            return f"Intensidad ligeramente inferior al objetivo en {metric_label}."
        return f"Intensidad cercana al objetivo en {metric_label}."
    if status == "failed":
        if direction == "above":
            return f"Intensidad superior a la esperada en {metric_label}."
        if direction == "below":
            return f"Intensidad por debajo de la esperada en {metric_label}."
        return f"Intensidad incorrecta en {metric_label}."
    return "No hay datos suficientes para validar intensidad."


def _intensity_fact(status: str, direction: str | None) -> str:
    if status == "correct":
        return "intensidad correcta"
    if status == "partial":
        if direction == "above":
            return "intensidad apenas por encima del objetivo"
        if direction == "below":
            return "intensidad apenas por debajo del objetivo"
        return "intensidad parcial"
    if status == "failed":
        if direction == "above":
            return "intensidad superior al objetivo"
        if direction == "below":
            return "intensidad inferior al objetivo"
        return "intensidad incorrecta"
    return "intensidad con datos insuficientes"


def _intensity_context_notes(
    intensity_plan: dict[str, Any],
    status: str,
    direction: str | None,
    health_metric: DailyHealthMetric | None,
    weather: ActivityWeather | None,
) -> list[str]:
    notes: list[str] = []
    if intensity_plan["metric_key"] == "hr" and direction == "above":
        if weather and weather.temperature_start_c is not None and weather.temperature_start_c >= 28:
            notes.append("FC elevada posiblemente influida por temperatura alta.")
        if health_metric and health_metric.sleep_hours is not None and health_metric.sleep_hours < 6:
            notes.append("Intensidad alta con descanso previo limitado.")
        if health_metric and health_metric.body_battery_start is not None and health_metric.body_battery_start < 40:
            notes.append("Intensidad exigente con Body Battery bajo al inicio del dia.")
    if intensity_plan["metric_key"] == "power" and status == "failed" and weather and weather.wind_speed_start_kmh is not None and weather.wind_speed_start_kmh >= 25:
        notes.append("La potencia pudo verse afectada por viento fuerte.")
    return notes


def _infer_intensity_level(target_notes: str | None) -> str | None:
    if not target_notes:
        return None
    text = target_notes.strip().lower()
    if any(word in text for word in ("suave", "base")):
        return "low"
    if "tempo" in text:
        return "medium"
    if "fuerte" in text:
        return "high"
    return None


def _resolve_hr_range(max_hr: int | None, zone_label: str) -> tuple[float, float] | None:
    explicit = _parse_explicit_range(zone_label)
    if explicit is not None:
        return explicit
    zone = _parse_zone_label(zone_label)
    if zone is None or not max_hr:
        return None
    zone_map = {
        1: (0.50, 0.60),
        2: (0.60, 0.70),
        3: (0.70, 0.80),
        4: (0.80, 0.90),
        5: (0.90, 1.00),
    }
    lower, upper = zone_map.get(zone, (0.60, 0.70))
    return max_hr * lower, max_hr * upper


def _resolve_power_range(ftp: int | None, zone_label: str) -> tuple[float, float] | None:
    explicit = _parse_explicit_range(zone_label)
    if explicit is not None:
        return explicit
    zone = _parse_zone_label(zone_label)
    if zone is None or not ftp:
        return None
    zone_map = {
        1: (0.00, 0.55),
        2: (0.56, 0.75),
        3: (0.76, 0.90),
        4: (0.91, 1.05),
        5: (1.06, 1.20),
    }
    lower, upper = zone_map.get(zone, (0.56, 0.75))
    return ftp * lower, ftp * upper


def _range_from_intensity_level(level: str, anchor: float, *, metric: str) -> tuple[float, float] | None:
    if metric == "hr":
        mapping = {
            "low": (0.60, 0.75),
            "medium": (0.76, 0.87),
            "high": (0.88, 1.00),
        }
    elif metric == "power":
        mapping = {
            "low": (0.55, 0.75),
            "medium": (0.76, 0.90),
            "high": (0.91, 1.10),
        }
    elif metric == "pace":
        mapping = {
            "low": (1.12, 1.35),
            "medium": (1.02, 1.12),
            "high": (0.85, 1.02),
        }
    else:
        return None
    lower_mult, upper_mult = mapping[level]
    lower = anchor * lower_mult
    upper = anchor * upper_mult
    if lower > upper:
        lower, upper = upper, lower
    return lower, upper


def _parse_zone_label(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("zone", "z").replace(" ", "")
    for digit in ("1", "2", "3", "4", "5"):
        if f"z{digit}" in normalized:
            return int(digit)
    if normalized.isdigit():
        return int(normalized)
    return None


def _parse_explicit_range(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    cleaned = value.strip().lower().replace("bpm", "").replace("w", "").replace("s/km", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*[-/]\s*(\d+(?:\.\d+)?)", cleaned)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _normalize_sport(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "running": "run",
        "run": "run",
        "cycling": "bike",
        "bike": "bike",
        "swimming": "swim",
        "swim": "swim",
    }
    return aliases.get(normalized, normalized)
