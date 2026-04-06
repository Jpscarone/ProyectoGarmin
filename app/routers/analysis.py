from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from urllib.parse import quote
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.db.session import get_db
from app.services.analysis.bundle_service import (
    build_bundle_for_activity,
    build_bundle_for_report,
    build_bundle_for_session,
)
from app.services.analysis.report_service import (
    analyze_training_day,
    get_analysis_report,
    update_final_conclusion,
)
from app.services.analysis.session_analysis_service import (
    analyze_activity_session,
    analyze_planned_session,
)
from app.services.analysis_v2.weekly_analysis_service import (
    ANALYSIS_VERSION as WEEKLY_ANALYSIS_VERSION,
    build_week_context,
    compute_week_metrics,
    re_run_weekly_analysis,
)
from app.web.templates import build_templates


router = APIRouter(prefix="/analysis", tags=["analysis"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("/weekly/{athlete_id}/{week_start_date}", response_class=HTMLResponse)
def read_weekly_analysis_v2(
    athlete_id: int,
    week_start_date: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    normalized_week_start = _parse_week_start_or_404(week_start_date)
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    analysis = _get_weekly_analysis_v2(db, athlete_id, normalized_week_start)
    preview_context = None
    preview_metrics = None
    if analysis is None:
        try:
            preview_context = build_week_context(db, athlete_id, normalized_week_start)
            preview_metrics = compute_week_metrics(preview_context)
        except Exception:
            preview_context = None
            preview_metrics = None

    view_model = _build_weekly_analysis_v2_view_model(
        athlete=athlete,
        week_start_date=normalized_week_start,
        analysis=analysis,
        preview_context=preview_context,
        preview_metrics=preview_metrics,
    )

    return templates.TemplateResponse(
        request=request,
        name="analysis/weekly_detail_v2.html",
        context={
            "athlete": athlete,
            "analysis": analysis,
            "view_model": view_model,
            "status_message": request.query_params.get("status"),
        },
    )


@router.post("/weekly/{athlete_id}/{week_start_date}/re-run")
def rerun_weekly_analysis_v2(
    athlete_id: int,
    week_start_date: str,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    normalized_week_start = _parse_week_start_or_404(week_start_date)
    analysis = re_run_weekly_analysis(
        db,
        athlete_id=athlete_id,
        reference_date=normalized_week_start,
        trigger_source="manual_reanalysis",
    )
    return RedirectResponse(
        url=f"/analysis/weekly/{athlete_id}/{normalized_week_start.isoformat()}?status={quote(f'Analisis semanal actualizado ({analysis.status}).')}",
        status_code=303,
    )


@router.get("/{report_id}", response_class=HTMLResponse)
def read_analysis_report(report_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    report = get_analysis_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis report not found")
    report_view = _build_analysis_report_view_model(report)
    return templates.TemplateResponse(
        request=request,
        name="analysis/detail.html",
        context={"report": report, "report_view": report_view, "status_message": request.query_params.get("status")},
    )


@router.post("/session/{planned_session_id}")
def analyze_session_endpoint(planned_session_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        report = analyze_planned_session(db, planned_session_id)
        return RedirectResponse(url=f"/analysis/{report.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/planned_sessions/{planned_session_id}?analysis_status={quote(str(exc))}",
            status_code=303,
        )


@router.post("/activity/{activity_id}")
def analyze_activity_endpoint(activity_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        report = analyze_activity_session(db, activity_id)
        return RedirectResponse(url=f"/analysis/{report.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/activities/{activity_id}?analysis_status={quote(str(exc))}",
            status_code=303,
        )


@router.post("/day/{training_day_id}")
def analyze_day_endpoint(training_day_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        report = analyze_training_day(db, training_day_id)
        return RedirectResponse(url=f"/analysis/{report.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/training_days/{training_day_id}?analysis_status={quote(str(exc))}",
            status_code=303,
        )


@router.post("/{report_id}/conclusion")
def save_final_conclusion(
    report_id: int,
    final_conclusion_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    report = get_analysis_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis report not found")
    update_final_conclusion(db, report, final_conclusion_text)
    return RedirectResponse(
        url=f"/analysis/{report_id}?status={quote('Conclusion final guardada.')}",
        status_code=303,
    )


@router.get("/bundle/session/{planned_session_id}", response_class=HTMLResponse)
def session_bundle_view(planned_session_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        bundle = build_bundle_for_session(db, planned_session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="analysis/bundle.html",
        context={"bundle": bundle, "back_url": f"/planned_sessions/{planned_session_id}"},
    )


@router.get("/bundle/activity/{activity_id}", response_class=HTMLResponse)
def activity_bundle_view(activity_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        bundle = build_bundle_for_activity(db, activity_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="analysis/bundle.html",
        context={"bundle": bundle, "back_url": f"/activities/{activity_id}"},
    )


@router.get("/bundle/report/{report_id}", response_class=HTMLResponse)
def report_bundle_view(report_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        bundle = build_bundle_for_report(db, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="analysis/bundle.html",
        context={"bundle": bundle, "back_url": f"/analysis/{report_id}"},
    )


def _parse_week_start_or_404(raw_value: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="week_start_date invalida") from exc


def _get_weekly_analysis_v2(db: Session, athlete_id: int, week_start_date: date) -> WeeklyAnalysis | None:
    return db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start_date,
            WeeklyAnalysis.analysis_version == WEEKLY_ANALYSIS_VERSION,
        )
        .order_by(WeeklyAnalysis.id.desc())
    )


def _build_weekly_analysis_v2_view_model(
    *,
    athlete: Athlete,
    week_start_date: date,
    analysis: WeeklyAnalysis | None,
    preview_context: Any,
    preview_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics_payload = analysis.metrics_json if analysis and isinstance(analysis.metrics_json, dict) else {}
    context_payload = metrics_payload.get("context", {}) if isinstance(metrics_payload, dict) else {}
    metrics = metrics_payload.get("metrics", {}) if isinstance(metrics_payload, dict) else {}
    if not metrics and preview_metrics:
        metrics = preview_metrics
    if not context_payload and preview_context is not None:
        context_payload = preview_context.to_dict()

    structured_output = (
        analysis.llm_json.get("structured_output", {})
        if analysis and isinstance(analysis.llm_json, dict)
        else {}
    )
    status_value = analysis.status if analysis else "missing"
    week_end_date = week_start_date + timedelta(days=6)
    totals = metrics.get("totals", {})
    scores = metrics.get("scores", {})
    compliance = metrics.get("compliance", {})
    trends = metrics.get("trends", {})
    technical = _build_weekly_technical_view(
        metrics_payload=metrics_payload,
        context_payload=context_payload,
        analysis=analysis,
        preview_metrics=preview_metrics,
    )

    return {
        "state": {
            "status": status_value,
            "is_error": status_value == "error",
            "is_pending": status_value in {"pending", "missing"},
            "message": _weekly_state_message(status_value, analysis.error_message if analysis else None),
        },
        "header": {
            "title": f"Semana del {week_start_date.strftime('%d/%m/%Y')}",
            "subtitle": athlete.name or f"Atleta #{athlete.id}",
            "week_range": f"{week_start_date.strftime('%d/%m')} al {week_end_date.strftime('%d/%m/%Y')}",
            "week_start_date": week_start_date.isoformat(),
            "status_label": _weekly_status_label(status_value),
            "status_class": _weekly_status_class(status_value),
            "totals": [
                {"label": "Duracion total", "value": _duration_seconds_label(totals.get("total_duration_sec"))},
                {"label": "Distancia total", "value": _distance_m_label(totals.get("total_distance_m"))},
                {"label": "Desnivel", "value": _elevation_label(totals.get("total_elevation_gain_m"))},
                {"label": "Sesiones", "value": str(totals.get("activity_count") or 0)},
            ],
        },
        "conclusion": analysis.coach_conclusion if analysis and analysis.coach_conclusion else _weekly_empty_conclusion(status_value),
        "summary_short": analysis.summary_short if analysis and analysis.summary_short else _weekly_empty_summary(status_value),
        "scores": [
            _score_card("Carga", analysis.load_score if analysis else scores.get("load_score")),
            _score_card("Consistencia", analysis.consistency_score if analysis else scores.get("consistency_score")),
            _score_card("Fatiga", analysis.fatigue_score if analysis else scores.get("fatigue_score")),
            _score_card("Balance", analysis.balance_score if analysis else scores.get("balance_score")),
        ],
        "positives": structured_output.get("positives") or [],
        "risks": structured_output.get("risks") or [],
        "recommendation": analysis.next_week_recommendation if analysis and analysis.next_week_recommendation else _weekly_empty_recommendation(status_value),
        "week_type_detected": structured_output.get("week_type_detected") or "-",
        "main_findings": structured_output.get("main_findings") or [],
        "tags": structured_output.get("tags") or [],
        "compliance": {
            "planned": compliance.get("planned_sessions"),
            "completed": compliance.get("completed_sessions"),
            "ratio_pct": _percentage_label(compliance.get("compliance_ratio_pct")),
        },
        "charts": _build_weekly_chart_data(metrics),
        "comparisons": _build_weekly_comparison_view(trends),
        "technical": technical,
    }


def _weekly_status_label(status_value: str) -> str:
    return {
        "completed": "Completo",
        "completed_with_warnings": "Completo con advertencias",
        "error": "Error",
        "pending": "Pendiente",
        "missing": "Sin analisis",
    }.get(status_value, status_value or "Sin analisis")


def _weekly_status_class(status_value: str) -> str:
    return {
        "completed": "analysis-status-good",
        "completed_with_warnings": "analysis-status-warn",
        "error": "analysis-status-bad",
        "pending": "analysis-status-neutral",
        "missing": "analysis-status-neutral",
    }.get(status_value, "analysis-status-neutral")


def _weekly_state_message(status_value: str, error_message: str | None) -> str:
    if status_value == "error":
        return error_message or "Hubo un error al generar el analisis semanal."
    if status_value == "missing":
        return "Analisis pendiente. Esta semana todavia no tiene un WeeklyAnalysis V2 guardado."
    if status_value == "pending":
        return "Analisis semanal en preparacion."
    if status_value == "completed_with_warnings":
        return "El analisis semanal esta disponible, pero algunas partes se resolvieron con fallback o datos incompletos."
    return ""


def _weekly_empty_conclusion(status_value: str) -> str:
    if status_value == "error":
        return "No se pudo completar la lectura semanal."
    if status_value in {"pending", "missing"}:
        return "Todavia no hay una conclusion semanal disponible."
    return "No hay conclusion semanal disponible."


def _weekly_empty_summary(status_value: str) -> str:
    if status_value == "error":
        return "Analisis semanal interrumpido por un error."
    return "Todavia no hay un resumen semanal disponible."


def _weekly_empty_recommendation(status_value: str) -> str:
    if status_value == "error":
        return "Reintentar el analisis semanal cuando el servicio vuelva a estar disponible."
    return "Todavia no hay recomendacion para la proxima semana."


def _score_card(label: str, value: float | None) -> dict[str, Any]:
    if value is None:
        return {"label": label, "value": "-", "class": "score-card-neutral"}
    if value >= 80:
        css_class = "score-card-good"
    elif value >= 60:
        css_class = "score-card-warn"
    else:
        css_class = "score-card-bad"
    return {"label": label, "value": round(value), "class": css_class}


def _build_weekly_chart_data(metrics: dict[str, Any]) -> dict[str, Any]:
    totals = metrics.get("totals", {})
    distribution = metrics.get("distribution", {})
    trends = metrics.get("trends", {})

    daily_duration = totals.get("daily_duration_sec", {}) or {}
    daily_labels: list[str] = []
    daily_values: list[float] = []
    for iso_date in sorted(daily_duration.keys()):
        day = date.fromisoformat(iso_date)
        daily_labels.append(day.strftime("%a %d"))
        daily_values.append(round((daily_duration[iso_date] or 0) / 3600.0, 2))

    previous_weeks = trends.get("previous_weeks", []) or []
    volume_labels = [f"{date.fromisoformat(item['week_start_date']).strftime('%d/%m')}" for item in previous_weeks]
    volume_values = [round((item.get("total_duration_sec") or 0) / 3600.0, 2) for item in previous_weeks]
    if totals.get("total_duration_sec") is not None:
        volume_labels.append("Actual")
        volume_values.append(round((totals.get("total_duration_sec") or 0) / 3600.0, 2))

    sport_counts = ((distribution.get("sessions_by_sport") or {}).get("counts")) or {}
    zone_values = distribution.get("time_in_zones_sec") or {}
    intensity_values = distribution.get("intensity_distribution") or {}

    return {
        "show_daily_load": any(daily_values),
        "show_volume": any(volume_values),
        "show_sports": bool(sport_counts),
        "show_intensity": bool(zone_values) or bool(intensity_values),
        "daily_load": {"labels": daily_labels, "values": daily_values},
        "volume": {"labels": volume_labels, "values": volume_values},
        "sports": {"labels": list(sport_counts.keys()), "values": list(sport_counts.values())},
        "intensity": {
            "labels": list(zone_values.keys()) if zone_values else list(intensity_values.keys()),
            "values": list(zone_values.values()) if zone_values else list(intensity_values.values()),
        },
    }


def _build_weekly_comparison_view(trends: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in trends.get("previous_weeks", []) or []:
        rows.append(
            {
                "range": f"{_format_iso_date(item.get('week_start_date'))} - {_format_iso_date(item.get('week_end_date'))}",
                "duration": _duration_seconds_label(item.get("total_duration_sec")),
                "distance": _distance_m_label(item.get("total_distance_m")),
                "elevation": _elevation_label(item.get("total_elevation_gain_m")),
                "activities": str(item.get("activity_count") or 0),
            }
        )
    return {
        "summary": [
            {"label": "Duracion vs promedio", "value": _signed_percentage_label(trends.get("duration_vs_prev_avg_pct"))},
            {"label": "Distancia vs promedio", "value": _signed_percentage_label(trends.get("distance_vs_prev_avg_pct"))},
            {"label": "Desnivel vs promedio", "value": _signed_percentage_label(trends.get("elevation_vs_prev_avg_pct"))},
            {"label": "Sesiones vs promedio", "value": _signed_percentage_label(trends.get("activity_count_vs_prev_avg_pct"))},
        ],
        "rows": rows,
    }


def _build_weekly_technical_view(
    metrics_payload: dict[str, Any],
    context_payload: dict[str, Any],
    analysis: WeeklyAnalysis | None,
    preview_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    activities = context_payload.get("activities") or []
    planned = context_payload.get("planned_sessions") or []
    health_days = context_payload.get("health_days") or []
    return {
        "metrics_pretty": json.dumps(
            metrics_payload.get("metrics", {}) if metrics_payload else (preview_metrics or {}),
            ensure_ascii=False,
            indent=2,
        ),
        "llm_pretty": json.dumps(analysis.llm_json if analysis and isinstance(analysis.llm_json, dict) else {}, ensure_ascii=False, indent=2),
        "activities": [
            {
                "date": _format_iso_date(item.get("activity_date")),
                "title": item.get("title") or "-",
                "sport": item.get("sport_type") or "-",
                "duration": _duration_seconds_label(item.get("duration_sec")),
                "distance": _distance_m_label(item.get("distance_m")),
                "avg_hr": _value_or_dash(item.get("avg_hr")),
            }
            for item in activities
        ],
        "planned": [
            {
                "date": _format_iso_date(item.get("session_date")),
                "title": item.get("title") or "-",
                "sport": item.get("sport_type") or "-",
                "duration": _duration_minutes_label(item.get("expected_duration_min")),
                "distance": _distance_km_label(item.get("expected_distance_km")),
                "matched": "Si" if item.get("matched") else "No",
            }
            for item in planned
        ],
        "health_days": [
            {
                "date": _format_iso_date(item.get("metric_date")),
                "sleep": _value_or_dash(item.get("sleep_hours")),
                "stress": _value_or_dash(item.get("stress_avg")),
                "body_battery": _value_or_dash(item.get("body_battery_end")),
                "hrv": _value_or_dash(item.get("hrv_avg_ms")),
            }
            for item in health_days
        ],
    }


def _duration_seconds_label(value: int | None) -> str:
    if value is None:
        return "-"
    total_minutes = int(round(value / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d} h"
    return f"{minutes} min"


def _duration_minutes_label(value: int | None) -> str:
    if value is None:
        return "-"
    hours, minutes = divmod(int(value), 60)
    if hours:
        return f"{hours}:{minutes:02d} h"
    return f"{minutes} min"


def _distance_m_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value / 1000.0:.1f} km" if value >= 1000 else f"{round(value)} m"


def _distance_km_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f} km" if value >= 1 else f"{round(value * 1000)} m"


def _elevation_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{round(value)} m+"


def _percentage_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{round(value)}%"


def _signed_percentage_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}%"


def _format_iso_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _value_or_dash(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _build_analysis_report_view_model(report: Any) -> dict[str, Any]:
    context = _parse_report_context(report.analysis_context_json)
    structured_summary = context.get("structured_summary", {}) if isinstance(context, dict) else {}
    planned_vs_actual = structured_summary.get("planned_vs_actual", {}) if isinstance(structured_summary, dict) else {}
    blocks = structured_summary.get("blocks", {}) if isinstance(structured_summary, dict) else {}

    highlights = []
    for label, payload, unit in (
        ("Duracion", planned_vs_actual.get("duration"), "min"),
        ("Distancia", planned_vs_actual.get("distance"), "km"),
        ("Desnivel", planned_vs_actual.get("elevation"), "m"),
    ):
        if not isinstance(payload, dict):
            continue
        if payload.get("planned") is None and payload.get("actual") is None:
            continue
        highlights.append(
            {
                "label": label,
                "planned": _metric_with_unit(payload.get("planned"), unit),
                "actual": _metric_with_unit(payload.get("actual"), unit),
                "difference": _signed_metric_with_unit(payload.get("difference"), unit),
                "difference_pct": _signed_percentage_label(payload.get("difference_pct")),
            }
        )

    block_rows = blocks.get("rows", []) if isinstance(blocks, dict) else []
    return {
        "conclusion": report.final_conclusion_text,
        "highlights": highlights,
        "blocks": {
            "matched_count": blocks.get("matched_count") if isinstance(blocks, dict) else 0,
            "missing_planned_steps": blocks.get("missing_planned_steps") if isinstance(blocks, dict) else 0,
            "extra_laps": blocks.get("extra_laps") if isinstance(blocks, dict) else 0,
            "rows": block_rows,
        },
        "structured_summary": structured_summary,
        "context_pretty": json.dumps(context, ensure_ascii=False, indent=2) if context else "-",
    }


def _parse_report_context(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _metric_with_unit(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    return f"{value} {unit}"


def _signed_metric_with_unit(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    numeric = float(value)
    prefix = "+" if numeric > 0 else ""
    if numeric.is_integer():
        return f"{prefix}{int(numeric)} {unit}"
    return f"{prefix}{numeric:.1f} {unit}"
