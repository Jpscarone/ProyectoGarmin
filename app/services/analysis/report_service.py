from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.analysis_report import AnalysisReport
from app.db.models.analysis_report_item import AnalysisReportItem
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.services.analysis.comparator import compare_planned_session_to_activity
from app.services.analysis.recommendations import build_recommendation_text, build_summary_text


def get_analysis_report(db: Session, report_id: int) -> AnalysisReport | None:
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
            selectinload(AnalysisReport.session_group),
        )
    )
    return db.scalar(statement)


def get_latest_session_report(db: Session, planned_session_id: int) -> AnalysisReport | None:
    statement = (
        select(AnalysisReport)
        .where(
            AnalysisReport.report_type == "session",
            AnalysisReport.planned_session_id == planned_session_id,
        )
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    return db.scalar(statement)


def get_latest_activity_report(db: Session, activity_id: int) -> AnalysisReport | None:
    statement = (
        select(AnalysisReport)
        .where(
            AnalysisReport.report_type == "session",
            AnalysisReport.garmin_activity_id_fk == activity_id,
        )
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    return db.scalar(statement)


def get_latest_day_report(db: Session, training_day_id: int) -> AnalysisReport | None:
    statement = (
        select(AnalysisReport)
        .where(
            AnalysisReport.report_type == "day_summary",
            AnalysisReport.training_day_id == training_day_id,
        )
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    return db.scalar(statement)


def update_final_conclusion(db: Session, report: AnalysisReport, final_conclusion_text: str | None) -> AnalysisReport:
    report.final_conclusion_text = final_conclusion_text.strip() if final_conclusion_text and final_conclusion_text.strip() else None
    db.add(report)
    db.commit()
    db.refresh(report)
    return get_analysis_report(db, report.id) or report


def analyze_session(db: Session, planned_session_id: int) -> AnalysisReport:
    planned_session = _get_planned_session_for_analysis(db, planned_session_id)
    if planned_session is None:
        raise ValueError("Planned session not found")

    activity = planned_session.activity_match.garmin_activity if planned_session.activity_match else None
    health_metric = _get_health_metric_for_session(db, planned_session)
    weather = activity.weather if activity else None

    comparison = compare_planned_session_to_activity(planned_session, activity, health_metric, weather)
    has_step_failures = any(item["item_status"] in {"failed", "skipped"} for item in comparison.item_rows)
    summary_text = build_summary_text(comparison.overall_status, comparison.summary_facts, comparison.context_notes)
    recommendation_text = build_recommendation_text(comparison.overall_status, comparison.context_notes, has_step_failures)

    report = _find_or_create_session_report(db, planned_session, activity)
    report.athlete_id = planned_session.athlete_id
    report.report_type = "session"
    report.training_day_id = planned_session.training_day_id
    report.session_group_id = planned_session.session_group_id
    report.planned_session_id = planned_session.id
    report.garmin_activity_id_fk = activity.id if activity else None
    report.title = comparison.title
    report.overall_score = comparison.overall_score
    report.overall_status = comparison.overall_status
    report.summary_text = summary_text
    report.recommendation_text = recommendation_text
    report.analysis_context_json = json.dumps(
        {
            **comparison.analysis_context,
            "summary_facts": comparison.summary_facts,
            "context_notes": comparison.context_notes,
            "score_breakdown": _score_breakdown_from_items(comparison.item_rows),
        },
        ensure_ascii=True,
        default=str,
    )

    _replace_report_items(report, comparison.item_rows)
    db.add(report)
    db.commit()
    db.refresh(report)
    return get_analysis_report(db, report.id) or report


def analyze_activity(db: Session, activity_id: int) -> AnalysisReport:
    activity = _get_activity_for_analysis(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found")

    if activity.activity_match and activity.activity_match.planned_session:
        return analyze_session(db, activity.activity_match.planned_session.id)

    report = _find_or_create_activity_only_report(db, activity)
    report.athlete_id = activity.athlete_id
    report.report_type = "session"
    report.training_day_id = activity.activity_match.training_day_id_fk if activity.activity_match else None
    report.session_group_id = None
    report.planned_session_id = None
    report.garmin_activity_id_fk = activity.id
    report.title = f"Analisis de actividad: {activity.activity_name or activity.id}"
    report.overall_score = None
    report.overall_status = "review"
    report.summary_text = "La actividad no tiene una sesion planificada vinculada, por lo que el analisis queda en revision."
    report.recommendation_text = "Primero vincular la actividad con una sesion planificada para obtener un analisis comparativo."
    report.analysis_context_json = json.dumps({"garmin_activity_id": activity.id}, ensure_ascii=True, default=str)
    _replace_report_items(
        report,
        [
            {
                "item_order": 1,
                "item_type": "note",
                "reference_label": "Sin sesion vinculada",
                "planned_value_text": None,
                "actual_value_text": activity.activity_name or str(activity.id),
                "item_score": None,
                "item_status": "review",
                "comment_text": "No se encontro una sesion planificada vinculada a esta actividad.",
            }
        ],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return get_analysis_report(db, report.id) or report


def analyze_training_day(db: Session, training_day_id: int) -> AnalysisReport:
    training_day = _get_training_day_for_analysis(db, training_day_id)
    if training_day is None:
        raise ValueError("Training day not found")

    session_reports: list[AnalysisReport] = []
    item_rows: list[dict[str, Any]] = []
    for index, planned_session in enumerate(training_day.planned_sessions, start=1):
        session_report = analyze_session(db, planned_session.id)
        session_reports.append(session_report)
        item_rows.append(
            {
                "item_order": index,
                "item_type": "segment",
                "reference_label": planned_session.name,
                "planned_value_text": _session_day_planned_text(planned_session),
                "actual_value_text": (
                    _session_day_actual_text(session_report.garmin_activity)
                    if session_report.garmin_activity is not None
                    else "Sin actividad vinculada"
                ),
                "item_score": session_report.overall_score,
                "item_status": session_report.overall_status if session_report.overall_status in {"correct", "partial", "review"} else "failed",
                "comment_text": session_report.summary_text,
            }
        )

    usable_scores = [report.overall_score for report in session_reports if report.overall_score is not None]
    overall_score = round(sum(usable_scores) / len(usable_scores), 1) if usable_scores else None
    overall_status = "review" if not session_reports else (
        "correct" if overall_score is not None and overall_score >= 85 else
        "partial" if overall_score is not None and overall_score >= 60 else
        "not_completed" if overall_score is not None else
        "review"
    )

    report = _find_or_create_day_report(db, training_day)
    report.athlete_id = training_day.athlete_id
    report.report_type = "day_summary"
    report.training_day_id = training_day.id
    report.session_group_id = None
    report.planned_session_id = None
    report.garmin_activity_id_fk = None
    report.title = f"Resumen del dia {training_day.day_date}"
    report.overall_score = overall_score
    report.overall_status = overall_status
    report.summary_text = _build_day_summary_text(training_day, session_reports, overall_status)
    report.recommendation_text = _build_day_recommendation_text(session_reports, overall_status)
    report.analysis_context_json = json.dumps(
        {
            "training_day_id": training_day.id,
            "session_report_ids": [item.id for item in session_reports],
            "score_breakdown": _score_breakdown_from_items(item_rows),
        },
        ensure_ascii=True,
        default=str,
    )

    _replace_report_items(report, item_rows)
    db.add(report)
    db.commit()
    db.refresh(report)
    return get_analysis_report(db, report.id) or report


def _replace_report_items(report: AnalysisReport, item_rows: list[dict[str, Any]]) -> None:
    report.items.clear()
    for row in item_rows:
        report.items.append(
            AnalysisReportItem(
                item_order=row["item_order"],
                item_type=row["item_type"],
                reference_label=row.get("reference_label"),
                planned_value_text=row.get("planned_value_text"),
                actual_value_text=row.get("actual_value_text"),
                item_score=row.get("item_score"),
                item_status=row["item_status"],
                comment_text=row.get("comment_text"),
            )
        )


def _score_breakdown_from_items(item_rows: list[dict[str, Any]]) -> dict[str, float | None]:
    grouped: dict[str, list[float]] = {
        "score_duration": [],
        "score_distance": [],
        "score_intensity": [],
        "score_structure": [],
        "score_context": [],
    }
    for row in item_rows:
        score = row.get("item_score")
        if score is None:
            continue
        label = str(row.get("reference_label") or "").lower()
        item_type = str(row.get("item_type") or "").lower()
        if "duracion" in label:
            grouped["score_duration"].append(score)
        elif "distancia" in label or "elevacion" in label:
            grouped["score_distance"].append(score)
        elif "intensidad" in label or any(token in label for token in ("hr", "power", "pace", "cadencia")):
            grouped["score_intensity"].append(score)
        elif item_type in {"segment", "lap", "work", "warmup", "recovery", "cooldown", "steady"}:
            grouped["score_structure"].append(score)
        else:
            grouped["score_context"].append(score)
    breakdown = {key: _average_scores(values) for key, values in grouped.items()}
    breakdown["score_total"] = _average_scores([row.get("item_score") for row in item_rows])
    return breakdown


def _average_scores(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 1)


def _session_day_planned_text(planned_session: PlannedSession) -> str:
    parts: list[str] = []
    if planned_session.sport_type:
        parts.append(str(planned_session.sport_type).replace("_", " ").title())
    if planned_session.expected_duration_min:
        parts.append(f"{planned_session.expected_duration_min} min")
    if planned_session.expected_distance_km:
        parts.append(f"{planned_session.expected_distance_km} km")
    if planned_session.target_hr_zone:
        parts.append(f"FC {planned_session.target_hr_zone}")
    if planned_session.target_power_zone:
        parts.append(f"Pot {planned_session.target_power_zone}")
    if planned_session.target_notes:
        parts.append(planned_session.target_notes)
    return " | ".join(parts) or planned_session.name


def _session_day_actual_text(activity: GarminActivity | None) -> str:
    if activity is None:
        return "Sin actividad vinculada"
    parts: list[str] = []
    if activity.duration_sec:
        parts.append(f"{round(activity.duration_sec / 60.0, 1)} min")
    if activity.distance_m:
        parts.append(f"{round(activity.distance_m / 1000.0, 2)} km")
    if activity.avg_hr:
        parts.append(f"avg HR {activity.avg_hr}")
    if activity.avg_pace_sec_km:
        parts.append(f"pace {round(activity.avg_pace_sec_km)} s/km")
    return " | ".join(parts) or (activity.activity_name or "Actividad")


def _build_day_summary_text(training_day: TrainingDay, session_reports: list[AnalysisReport], overall_status: str) -> str:
    if not session_reports:
        return "No hay sesiones planificadas en este dia para analizar."
    if len(session_reports) == 1:
        report = session_reports[0]
        return f"Día {_status_text(overall_status)}: {report.summary_text or 'la unica sesion del dia no tiene suficiente informacion.'}"

    correct_count = sum(1 for report in session_reports if report.overall_status == "correct")
    partial_count = sum(1 for report in session_reports if report.overall_status == "partial")
    failed_count = sum(1 for report in session_reports if report.overall_status in {"failed", "not_completed"})
    review_count = sum(1 for report in session_reports if report.overall_status == "review")
    parts = [
        f"Dia {analysis_status_label(overall_status).lower()}: {correct_count} correctas",
        f"{partial_count} parciales",
        f"{failed_count} no completadas",
    ]
    if review_count:
        parts.append(f"{review_count} en revision")
    return ", ".join(parts) + "."


def _build_day_recommendation_text(session_reports: list[AnalysisReport], overall_status: str) -> str:
    if not session_reports:
        return "No hay sesiones para analizar en este dia."
    if overall_status == "correct":
        return "Mantener el plan del dia tal como estaba previsto."
    failed_reports = [report for report in session_reports if report.overall_status in {"failed", "not_completed"}]
    partial_reports = [report for report in session_reports if report.overall_status == "partial"]
    if failed_reports:
        return "Revisar primero las sesiones no completadas y confirmar si faltan actividades por vincular o si la ejecucion quedo realmente incompleta."
    if partial_reports:
        return "Revisar las sesiones parciales y confirmar si el desvio vino de duracion, distancia o intensidad antes de ajustar el plan."
    return "Hay datos en revision; conviene revisar match, zonas y actividad vinculada antes de sacar conclusiones."


def _status_text(value: str) -> str:
    mapping = {
        "correct": "correcto",
        "partial": "parcial",
        "review": "en revision",
        "failed": "fallido",
        "not_completed": "no completado",
        "skipped": "omitido",
    }
    return mapping.get(value, value)


def _find_or_create_session_report(db: Session, planned_session: PlannedSession, activity: GarminActivity | None) -> AnalysisReport:
    statement = (
        select(AnalysisReport)
        .where(
            AnalysisReport.report_type == "session",
            AnalysisReport.planned_session_id == planned_session.id,
        )
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    existing = db.scalar(statement)
    if existing is not None:
        return existing
    if activity is not None:
        statement = (
            select(AnalysisReport)
            .where(
                AnalysisReport.report_type == "session",
                AnalysisReport.garmin_activity_id_fk == activity.id,
            )
            .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
        )
        existing = db.scalar(statement)
        if existing is not None:
            return existing
    return AnalysisReport(athlete_id=planned_session.athlete_id, report_type="session", title=planned_session.name, overall_status="review")


def _find_or_create_activity_only_report(db: Session, activity: GarminActivity) -> AnalysisReport:
    statement = (
        select(AnalysisReport)
        .where(
            AnalysisReport.report_type == "session",
            AnalysisReport.garmin_activity_id_fk == activity.id,
            AnalysisReport.planned_session_id.is_(None),
        )
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    existing = db.scalar(statement)
    if existing is not None:
        return existing
    return AnalysisReport(athlete_id=activity.athlete_id, report_type="session", title=activity.activity_name or str(activity.id), overall_status="review")


def _find_or_create_day_report(db: Session, training_day: TrainingDay) -> AnalysisReport:
    statement = (
        select(AnalysisReport)
        .where(
            AnalysisReport.report_type == "day_summary",
            AnalysisReport.training_day_id == training_day.id,
        )
        .order_by(AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())
    )
    existing = db.scalar(statement)
    if existing is not None:
        return existing
    return AnalysisReport(athlete_id=training_day.athlete_id, report_type="day_summary", title=f"Resumen del dia {training_day.day_date}", overall_status="review")


def _get_planned_session_for_analysis(db: Session, planned_session_id: int) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .where(PlannedSession.id == planned_session_id)
        .options(
            selectinload(PlannedSession.athlete),
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


def _get_activity_for_analysis(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.laps),
            selectinload(GarminActivity.weather),
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
        )
    )
    return db.scalar(statement)


def _get_training_day_for_analysis(db: Session, training_day_id: int) -> TrainingDay | None:
    statement = (
        select(TrainingDay)
        .where(TrainingDay.id == training_day_id)
        .options(
            selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.activity_match)
            .selectinload(ActivitySessionMatch.garmin_activity),
        )
    )
    return db.scalar(statement)


def _get_health_metric_for_session(db: Session, planned_session: PlannedSession) -> DailyHealthMetric | None:
    statement = (
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == planned_session.athlete_id,
            DailyHealthMetric.metric_date == planned_session.training_day.day_date,
        )
        .order_by(DailyHealthMetric.metric_date.desc(), DailyHealthMetric.id.desc())
    )
    return db.scalar(statement)
