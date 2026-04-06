from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.analysis_report import AnalysisReport
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.services.analysis.report_service import analyze_session, get_analysis_report
from app.services.openai_client import OpenAIIntegrationError, generate_text_analysis


logger = logging.getLogger(__name__)


def analyze_planned_session(db: Session, planned_session_id: int) -> AnalysisReport:
    logger.info("Starting session analysis planned_session_id=%s", planned_session_id)
    planned_session = _get_planned_session_with_activity(db, planned_session_id)
    if planned_session is None:
        raise ValueError("Planned session not found.")

    activity = planned_session.activity_match.garmin_activity if planned_session.activity_match else None
    if activity is None:
        raise ValueError("La sesion no tiene una actividad vinculada para analizar.")

    report = analyze_session(db, planned_session_id)
    structured_summary = _build_structured_summary(planned_session, activity, report)
    prompt = build_session_analysis_prompt(
        planned_session=planned_session,
        activity=activity,
        report=report,
        structured_summary=structured_summary,
    )

    llm_state: dict[str, Any]
    try:
        logger.info("Generating OpenAI narrative for planned_session_id=%s report_id=%s", planned_session.id, report.id)
        final_conclusion_text = generate_text_analysis(prompt, analysis_type="session")
        llm_state = {"status": "completed"}
    except OpenAIIntegrationError as exc:
        logger.warning(
            "OpenAI session analysis fallback planned_session_id=%s report_id=%s error=%s",
            planned_session.id,
            report.id,
            exc,
        )
        final_conclusion_text = _build_fallback_conclusion(report)
        llm_state = {"status": "fallback", "error": str(exc)}

    existing_context = _load_context_json(report.analysis_context_json)
    existing_context["structured_summary"] = structured_summary
    existing_context["llm"] = llm_state

    report.final_conclusion_text = final_conclusion_text
    report.analysis_context_json = json.dumps(existing_context, ensure_ascii=True, default=str)
    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info("Finished session analysis planned_session_id=%s report_id=%s", planned_session.id, report.id)
    return get_analysis_report(db, report.id) or report


def analyze_activity_session(db: Session, activity_id: int) -> AnalysisReport:
    activity = _get_activity_with_match(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found.")
    if activity.activity_match is None or activity.activity_match.planned_session is None:
        raise ValueError("La actividad no tiene una sesion planificada vinculada para analizar.")
    return analyze_planned_session(db, activity.activity_match.planned_session.id)


def build_session_analysis_prompt(
    *,
    planned_session: PlannedSession,
    activity: GarminActivity,
    report: AnalysisReport,
    structured_summary: dict[str, Any],
) -> str:
    return build_session_coach_prompt(
        planned_session=planned_session,
        activity=activity,
        report=report,
        structured_summary=structured_summary,
    )


def build_session_coach_prompt(
    *,
    planned_session: PlannedSession,
    activity: GarminActivity,
    report: AnalysisReport,
    structured_summary: dict[str, Any],
) -> str:
    existing_context = _load_context_json(report.analysis_context_json)
    payload = {
        "sesion_planificada": {
            "id": planned_session.id,
            "nombre": planned_session.name,
            "fecha": planned_session.training_day.day_date.isoformat() if planned_session.training_day else None,
            "deporte": planned_session.sport_type,
            "descripcion": planned_session.description_text,
            "duracion_objetivo_min": planned_session.expected_duration_min,
            "distancia_objetivo_km": planned_session.expected_distance_km,
            "desnivel_objetivo_m": planned_session.expected_elevation_gain_m,
            "notas_objetivo": planned_session.target_notes,
        },
        "actividad_real": {
            "id": activity.id,
            "nombre": activity.activity_name,
            "deporte": activity.sport_type,
            "duracion_real_min": round((activity.duration_sec or 0) / 60.0, 1) if activity.duration_sec else None,
            "distancia_real_km": round((activity.distance_m or 0) / 1000.0, 2) if activity.distance_m else None,
            "desnivel_real_m": activity.elevation_gain_m,
            "fc_media": activity.avg_hr,
            "fc_maxima": activity.max_hr,
            "ritmo_medio_sec_km": round(activity.avg_pace_sec_km, 1) if activity.avg_pace_sec_km is not None else None,
            "potencia_media": activity.avg_power,
        },
        "comparacion": structured_summary,
        "scores_backend": {
            "score_general": report.overall_score,
            "estado_general": report.overall_status,
            "score_breakdown": existing_context.get("score_breakdown"),
        },
        "lectura_backend": {
            "desvios_principales": _collect_main_deviations(structured_summary),
            "puntos_fuertes": _collect_positive_signals(structured_summary, report),
            "alertas": _collect_alert_signals(structured_summary, report),
            "observaciones_bloques": _collect_block_observations(structured_summary),
            "notas_contexto": existing_context.get("context_notes"),
            "hechos_resumen": existing_context.get("summary_facts"),
        },
        "resumen_backend": report.summary_text,
        "recomendacion_backend": report.recommendation_text,
    }

    return (
        "Actua como un entrenador de endurance que interpreta una sesion ya analizada por el backend.\n"
        "No recalcules metricas ni inventes nada: solo interpreta y redacta con lenguaje humano.\n\n"
        "Quiero una devolucion en espanol natural, tecnica pero facil de entender, en 3 o 4 parrafos breves.\n"
        "No pongas titulos, no uses markdown, no uses bullets y no respondas en JSON.\n"
        "La respuesta debe sonar como una lectura de entrenador: clara, practica, con matices y sin rigidez.\n\n"
        "Que debe hacer la respuesta:\n"
        "- abrir con una lectura general de la sesion y su sentido\n"
        "- explicar que salio bien o que quedo bien orientado\n"
        "- explicar que se desvio, que quedo flojo o que habria que controlar mejor\n"
        "- cerrar con una recomendacion concreta o un aprendizaje util para la proxima sesion\n\n"
        "Que NO debe hacer:\n"
        "- no inventes datos faltantes ni sensaciones del atleta\n"
        "- no digas que algo fue excelente si los datos muestran problemas\n"
        "- no repitas literalmente toda la tabla de numeros que ya ve el usuario\n"
        "- no conviertas el dashboard en prosa mecanica\n"
        "- no uses frases vacias como gran trabajo, excelente esfuerzo, segui asi o muy bien hecho salvo que esten muy justificadas\n\n"
        "Favorece un lenguaje como:\n"
        "- la sesion en general quedo bien orientada\n"
        "- el bloque principal salio solido\n"
        "- el costo fisiologico fue algo mas alto de lo ideal\n"
        "- el cumplimiento fue bueno, pero el control no fue del todo fino\n"
        "- no invalida la sesion, pero si cambia la lectura\n"
        "- para la proxima convendria...\n\n"
        "Usa solamente los datos que siguen y prioriza interpretacion sobre repeticion:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
    )


def _collect_main_deviations(structured_summary: dict[str, Any]) -> list[str]:
    deviations: list[str] = []
    planned_vs_actual = structured_summary.get("planned_vs_actual", {})
    labels = {
        "duration": "duracion",
        "distance": "distancia",
        "elevation": "desnivel",
    }
    for key, label in labels.items():
        block = planned_vs_actual.get(key) or {}
        difference_pct = block.get("difference_pct")
        if difference_pct is None:
            continue
        if abs(difference_pct) >= 8:
            direction = "por encima" if difference_pct > 0 else "por debajo"
            deviations.append(f"{label} {direction} de lo previsto ({difference_pct:+.1f}%).")

    sport = structured_summary.get("sport") or {}
    if sport.get("match") is False:
        deviations.append("La actividad no coincide bien con el deporte planificado.")
    return deviations


def _collect_positive_signals(structured_summary: dict[str, Any], report: AnalysisReport) -> list[str]:
    positives: list[str] = []
    sport = structured_summary.get("sport") or {}
    if sport.get("match"):
        positives.append("El deporte realizado coincide con lo planificado.")

    planned_vs_actual = structured_summary.get("planned_vs_actual", {})
    labels = {
        "duration": "La duracion quedo cerca de lo previsto.",
        "distance": "La distancia quedo cerca de lo previsto.",
        "elevation": "El desnivel quedo razonablemente alineado con el plan.",
    }
    for key, text in labels.items():
        block = planned_vs_actual.get(key) or {}
        difference_pct = block.get("difference_pct")
        if difference_pct is not None and abs(difference_pct) <= 5:
            positives.append(text)

    blocks = structured_summary.get("blocks") or {}
    if blocks.get("matched_count") and not blocks.get("missing_planned_steps") and not blocks.get("extra_laps"):
        positives.append("La estructura de bloques y laps quedo bien alineada.")

    if report.overall_score is not None and report.overall_score >= 85:
        positives.append("El cumplimiento general fue alto.")

    return positives[:4]


def _collect_alert_signals(structured_summary: dict[str, Any], report: AnalysisReport) -> list[str]:
    alerts: list[str] = []
    blocks = structured_summary.get("blocks") or {}
    missing = blocks.get("missing_planned_steps") or 0
    extra = blocks.get("extra_laps") or 0
    if missing:
        alerts.append(f"Quedaron {missing} bloques sin lap equivalente.")
    if extra:
        alerts.append(f"Aparecieron {extra} laps extra sin bloque planificado.")

    planned_vs_actual = structured_summary.get("planned_vs_actual", {})
    for key, label in (("duration", "duracion"), ("distance", "distancia"), ("elevation", "desnivel")):
        block = planned_vs_actual.get(key) or {}
        difference_pct = block.get("difference_pct")
        if difference_pct is not None and abs(difference_pct) >= 15:
            alerts.append(f"El desvio de {label} fue relevante ({difference_pct:+.1f}%).")

    if report.overall_score is not None and report.overall_score < 60:
        alerts.append("El score general quedo bajo para una sesion bien ejecutada.")

    return alerts[:4]


def _collect_block_observations(structured_summary: dict[str, Any]) -> list[str]:
    observations: list[str] = []
    rows = (structured_summary.get("blocks") or {}).get("rows") or []
    for row in rows:
        status = row.get("status")
        label = row.get("label") or "Bloque"
        comment = row.get("comment")
        if status in {"failed", "skipped", "review", "partial"}:
            if comment:
                observations.append(f"{label}: {comment}")
            else:
                observations.append(f"{label}: estado {status}.")
    return observations[:5]


def determine_analysis_status(
    *,
    compliance_score: float | None,
    sport_match: bool,
    missing_planned_steps: int,
    extra_laps: int,
) -> str:
    if not sport_match:
        return "failed"
    if compliance_score is None:
        return "failed"
    if compliance_score >= 85 and missing_planned_steps == 0 and extra_laps == 0:
        return "success"
    if compliance_score >= 60:
        return "partial"
    return "failed"


def _build_structured_summary(
    planned_session: PlannedSession,
    activity: GarminActivity,
    report: AnalysisReport,
) -> dict[str, Any]:
    sport_match = _normalize_sport(planned_session.sport_type) == _normalize_sport(activity.sport_type)
    duration_real_min = round((activity.duration_sec or 0) / 60.0, 1) if activity.duration_sec is not None else None
    distance_real_km = round((activity.distance_m or 0) / 1000.0, 2) if activity.distance_m is not None else None
    blocks = _build_block_comparison(report)
    result_status = determine_analysis_status(
        compliance_score=report.overall_score,
        sport_match=sport_match,
        missing_planned_steps=blocks["missing_planned_steps"],
        extra_laps=blocks["extra_laps"],
    )

    return {
        "sport": {
            "planned": planned_session.sport_type,
            "actual": activity.sport_type,
            "match": sport_match,
        },
        "planned_vs_actual": {
            "duration": _build_delta_summary(planned_session.expected_duration_min, duration_real_min, precision=1),
            "distance": _build_delta_summary(planned_session.expected_distance_km, distance_real_km, precision=2),
            "elevation": _build_delta_summary(planned_session.expected_elevation_gain_m, activity.elevation_gain_m, precision=1),
        },
        "activity_metrics": {
            "avg_hr": activity.avg_hr,
            "max_hr": activity.max_hr,
            "avg_pace_sec_km": round(activity.avg_pace_sec_km, 1) if activity.avg_pace_sec_km is not None else None,
            "avg_power": activity.avg_power,
            "distance_km": distance_real_km,
            "duration_min": duration_real_min,
            "elevation_gain_m": round(activity.elevation_gain_m, 1) if activity.elevation_gain_m is not None else None,
        },
        "blocks": blocks,
        "compliance_score": report.overall_score,
        "compliance_score_formula": (
            "Score 0-100 calculado por el comparador backend: combina deporte, duracion, distancia, desnivel "
            "y cumplimiento de bloques/laps. Las metricas globales pesan mas que los detalles finos."
        ),
        "result_status": result_status,
    }


def _build_block_comparison(report: AnalysisReport) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    matched_count = 0
    missing_planned_steps = 0
    extra_laps = 0

    for item in report.items:
        reference_label = item.reference_label or item.item_type
        is_block_row = (
            reference_label.startswith("Step ")
            or reference_label.startswith("Lap ")
            or reference_label == "Sesion continua"
        )
        if not is_block_row:
            continue

        if " / Lap " in reference_label:
            matched_count += 1
        elif item.actual_value_text == "Sin lap correspondiente":
            missing_planned_steps += 1
        elif item.planned_value_text == "Sin step planificado":
            extra_laps += 1

        rows.append(
            {
                "label": reference_label,
                "planned": item.planned_value_text,
                "actual": item.actual_value_text,
                "status": item.item_status,
                "score": item.item_score,
                "comment": item.comment_text,
            }
        )

    return {
        "matched_count": matched_count,
        "missing_planned_steps": missing_planned_steps,
        "extra_laps": extra_laps,
        "rows": rows,
    }


def _build_delta_summary(expected: float | None, actual: float | None, *, precision: int) -> dict[str, float | None]:
    if expected is None or actual is None:
        return {
            "planned": expected,
            "actual": actual,
            "difference": None,
            "difference_abs": None,
            "difference_pct": None,
        }

    difference = actual - expected
    difference_pct = (difference / expected * 100.0) if expected else None
    return {
        "planned": round(expected, precision),
        "actual": round(actual, precision),
        "difference": round(difference, precision),
        "difference_abs": round(abs(difference), precision),
        "difference_pct": round(difference_pct, 1) if difference_pct is not None else None,
    }


def _build_fallback_conclusion(report: AnalysisReport) -> str:
    summary = (report.summary_text or "").strip()
    recommendation = (report.recommendation_text or "").strip()
    if summary and recommendation:
        return f"{summary} Recomendacion practica: {recommendation}"
    if summary:
        return summary
    if recommendation:
        return f"Recomendacion practica: {recommendation}"
    return "No se pudo generar una conclusion automatica detallada, pero el analisis estructurado si quedo disponible."


def _load_context_json(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("analysis_context_json no se pudo parsear; se recrea desde cero")
        return {}


def _normalize_sport(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "running": "run",
        "run": "run",
        "trail_running": "run",
        "trail_run": "run",
        "street_running": "run",
        "road_running": "run",
        "cycling": "bike",
        "bike": "bike",
        "road_cycling": "bike",
        "road_biking": "bike",
        "mountain_biking": "bike",
        "mountain_bike": "bike",
        "mtb": "bike",
        "swimming": "swim",
        "swim": "swim",
        "pool_swim": "swim",
        "open_water_swim": "swim",
    }
    return aliases.get(normalized, normalized)


def _get_planned_session_with_activity(db: Session, planned_session_id: int) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .where(PlannedSession.id == planned_session_id)
        .options(
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
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


def _get_activity_with_match(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
        )
    )
    return db.scalar(statement)
