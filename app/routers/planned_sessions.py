from __future__ import annotations

import json
import re
from datetime import date, time
from pathlib import Path
from urllib.parse import quote, urlsplit
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.db.models.session_analysis import SessionAnalysis
from app.db.session import get_db
from app.schemas.planned_session import PlannedSessionCreate, PlannedSessionRead, PlannedSessionUpdate
from app.schemas.planned_session_step import PlannedSessionStepCreate
from app.services.analysis_v2.session_analysis_service import ANALYSIS_VERSION, re_run_session_analysis
from app.services.intensity_target_service import normalize_step_target_fields
from app.services.planning.presentation import build_session_display_blocks_for_session, derive_session_metrics
from app.services.planning.quick_session_service import (
    SessionAdvancedData,
    create_session_from_quick_mode,
)
from app.services.planning.parser import parse_session_text
from app.services.planning.presentation import build_session_display_blocks
from app.services.planned_session_service import (
    create_planned_session,
    delete_planned_session,
    get_planned_session,
    get_planned_sessions,
    update_planned_session,
)
from app.services.planned_session_step_service import replace_steps_for_session
from app.services.session_group_service import create_inline_group
from app.services.training_day_service import create_training_day, get_training_day, get_training_day_by_plan_and_date
from app.services.training_plan_service import get_training_plan
from app.schemas.training_day import TrainingDayCreate
from app.ui.catalogs import INTENSITY_TARGET_LABELS, MATCH_METHOD_LABELS, SPORT_LABELS, STEP_TYPE_LABELS, label_for
from app.web.templates import build_templates


router = APIRouter(prefix="/planned_sessions", tags=["planned_sessions"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[PlannedSessionRead])
def list_planned_sessions(db: Session = Depends(get_db)) -> list[PlannedSessionRead]:
    return get_planned_sessions(db)


@router.get("/create", response_class=HTMLResponse)
def create_planned_session_page(
    training_day_id: int = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    return RedirectResponse(url=f"/planned_sessions/quick?training_day_id={training_day.id}&mode=builder#builder", status_code=303)


@router.get("/quick", response_class=HTMLResponse)
def create_quick_session_page(
    request: Request,
    training_day_id: int | None = Query(default=None),
    training_plan_id: int | None = Query(default=None),
    day_date: str | None = Query(default=None),
    planned_session_id: int | None = Query(default=None),
    mode: str | None = Query(default=None),
    session_group_id: int | None = Query(default=None),
    return_to: str | None = Query(default=None),
    month: str | None = Query(default=None),
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    editing_session = get_planned_session(db, planned_session_id) if planned_session_id is not None else None
    if planned_session_id is not None and editing_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesion no encontrada")

    training_day = editing_session.training_day if editing_session else (get_training_day(db, training_day_id) if training_day_id is not None else None)
    if training_day_id is not None and training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dia no encontrado")

    training_plan = training_day.training_plan if training_day else None
    selected_day_date: date | None = training_day.day_date if training_day else None

    if training_day is None:
        if training_plan_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta training_plan_id")
        training_plan = get_training_plan(db, training_plan_id)
        if training_plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")
        if day_date:
            try:
                selected_day_date = date.fromisoformat(day_date)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fecha invalida") from exc
            existing_day = get_training_day_by_plan_and_date(db, training_plan.id, selected_day_date)
            if existing_day is not None:
                training_day = existing_day

    requested_mode = (mode or _infer_quick_mode_for_planned_session(editing_session)).strip().lower()
    initial_mode = requested_mode if requested_mode in {"simple", "text", "builder"} else "simple"
    initial_session_group_id: int | None = None
    available_groups = training_day.session_groups if training_day else []
    if session_group_id is not None and any(group.id == session_group_id for group in available_groups):
        initial_session_group_id = session_group_id

    return templates.TemplateResponse(
        request=request,
        name="planned_sessions/quick.html",
        context={
            "training_day": training_day,
            "training_plan": training_plan,
            "selected_day_date": selected_day_date.isoformat() if selected_day_date else "",
            "session_groups": available_groups,
            "error": request.query_params.get("error"),
            "initial_mode": initial_mode,
            "initial_session_group_id": initial_session_group_id,
            "return_to": (return_to or "").strip().lower(),
            "return_month": month or "",
            "return_selected_date": selected_date or (selected_day_date.isoformat() if selected_day_date else ""),
            "editing_session": editing_session,
            "initial_quick_data": _build_initial_quick_data(editing_session, initial_mode) if editing_session else None,
        },
    )


@router.get("/{planned_session_id}", response_model=PlannedSessionRead)
def read_planned_session(planned_session_id: int, request: Request, db: Session = Depends(get_db)):
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    if _wants_html(request):
        linked_activity = (
            planned_session.activity_match.garmin_activity
            if planned_session.activity_match and planned_session.activity_match.garmin_activity
            else None
        )
        analysis_v2 = _get_preferred_session_analysis(db, planned_session.id, linked_activity.id if linked_activity else None)
        return templates.TemplateResponse(
            request=request,
            name="planned_sessions/detail.html",
            context={
                "planned_session": planned_session,
                "training_day": planned_session.training_day,
                "analysis_v2": analysis_v2,
                "session_view": _build_session_detail_view_model(planned_session, analysis_v2),
                "can_edit_session": linked_activity is None,
                "back_link": _build_planned_session_back_link(request, planned_session),
                "ui_status": request.query_params.get("ui_status"),
                "match_status": request.query_params.get("match_status"),
                "analysis_status": request.query_params.get("analysis_status"),
            },
        )
    return planned_session


@router.get("/{planned_session_id}/analysis", response_class=HTMLResponse)
def read_planned_session_analysis_v2(
    planned_session_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")

    linked_activity = (
        planned_session.activity_match.garmin_activity
        if planned_session.activity_match and planned_session.activity_match.garmin_activity
        else None
    )
    analysis = _get_preferred_session_analysis(db, planned_session_id, linked_activity.id if linked_activity else None)
    view_model = _build_session_analysis_v2_view_model(planned_session, linked_activity, analysis)

    return templates.TemplateResponse(
        request=request,
        name="analysis/session_detail_v2.html",
        context={
            "planned_session": planned_session,
            "training_day": planned_session.training_day,
            "linked_activity": linked_activity,
            "analysis_v2": analysis,
            "view_model": view_model,
            "status_message": request.query_params.get("status"),
        },
    )


@router.post("/{planned_session_id}/analysis/re-run")
def rerun_planned_session_analysis_v2(
    planned_session_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")

    linked_activity = (
        planned_session.activity_match.garmin_activity
        if planned_session.activity_match and planned_session.activity_match.garmin_activity
        else None
    )
    if linked_activity is None:
        return RedirectResponse(
            url=f"/planned_sessions/{planned_session_id}/analysis?status={quote('No hay actividad vinculada para reanalizar.')}",
            status_code=303,
        )

    analysis = re_run_session_analysis(
        db,
        planned_session_id=planned_session.id,
        activity_id=linked_activity.id,
        trigger_source="manual_reanalysis",
    )
    return RedirectResponse(
        url=f"/planned_sessions/{planned_session.id}/analysis?status={quote(f'Analisis actualizado ({analysis.status}).')}",
        status_code=303,
    )


def _get_preferred_session_analysis(
    db: Session,
    planned_session_id: int,
    linked_activity_id: int | None,
) -> SessionAnalysis | None:
    analyses = list(
        db.scalars(
            select(SessionAnalysis)
            .where(
                SessionAnalysis.planned_session_id == planned_session_id,
                SessionAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .options(selectinload(SessionAnalysis.activity))
            .order_by(SessionAnalysis.analyzed_at.desc(), SessionAnalysis.id.desc())
        ).all()
    )
    if not analyses:
        return None
    if linked_activity_id is not None:
        exact = next((item for item in analyses if item.activity_id == linked_activity_id), None)
        if exact is not None:
            return exact
    return analyses[0]


def _build_planned_session_back_link(request: Request, planned_session) -> dict[str, str]:
    training_day = planned_session.training_day
    if training_day is None:
        return {"label": "Volver", "url": "/training_plans"}

    return_to = (request.query_params.get("return_to") or "").strip().lower()
    month = request.query_params.get("month") or (
        training_day.day_date.strftime("%Y-%m") if training_day.day_date else ""
    )
    selected_date = request.query_params.get("selected_date") or (
        training_day.day_date.isoformat() if training_day.day_date else ""
    )
    training_plan = training_day.training_plan

    if return_to == "calendar" and training_plan is not None:
        query_parts: list[str] = []
        if month:
            query_parts.append(f"month={quote(month)}")
        if selected_date:
            query_parts.append(f"selected_date={quote(selected_date)}")
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        return {"label": "Volver", "url": f"/training_plans/{training_plan.id}/calendar{query}"}

    if return_to == "plan" and training_plan is not None:
        return {"label": "Volver", "url": f"/training_plans/{training_plan.id}"}

    if return_to == "day":
        return {"label": "Volver", "url": f"/training_days/{training_day.id}"}

    referer = request.headers.get("referer")
    if referer:
        referer_parts = urlsplit(referer)
        current_parts = urlsplit(str(request.url))
        if referer_parts.scheme == current_parts.scheme and referer_parts.netloc == current_parts.netloc:
            referer_path = referer_parts.path or ""
            current_path = current_parts.path or ""
            if referer_path and referer_path != current_path:
                referer_query = f"?{referer_parts.query}" if referer_parts.query else ""
                return {"label": "Volver", "url": f"{referer_path}{referer_query}"}

    return {"label": "Volver", "url": f"/training_days/{training_day.id}"}


def _build_session_analysis_v2_view_model(planned_session, linked_activity, analysis: SessionAnalysis | None) -> dict[str, Any]:
    status_value = analysis.status if analysis else "missing"
    metrics_payload = analysis.metrics_json if analysis and isinstance(analysis.metrics_json, dict) else {}
    metrics = metrics_payload.get("metrics", {}) if isinstance(metrics_payload, dict) else {}
    context_payload = metrics_payload.get("context", {}) if isinstance(metrics_payload, dict) else {}
    structured_output = (
        analysis.llm_json.get("structured_output", {})
        if analysis and isinstance(analysis.llm_json, dict)
        else {}
    )

    header = {
        "title": planned_session.name,
        "date_label": planned_session.training_day.day_date.strftime("%d/%m/%Y") if planned_session.training_day and planned_session.training_day.day_date else "-",
        "sport_label": _sport_label(planned_session.sport_type),
        "duration_label": _duration_minutes_label(planned_session.expected_duration_min),
        "distance_label": _distance_km_label(planned_session.expected_distance_km),
        "status_label": _analysis_v2_status_label(status_value),
        "status_class": _analysis_v2_status_class(status_value),
    }

    conclusion = {
        "coach_conclusion": analysis.coach_conclusion if analysis and analysis.coach_conclusion else _empty_conclusion_copy(status_value),
        "summary_short": analysis.summary_short if analysis and analysis.summary_short else _empty_summary_copy(status_value),
    }

    scores = [
        _score_card("Cumplimiento", analysis.compliance_score if analysis else None),
        _score_card("Ejecucion", analysis.execution_score if analysis else None),
        _score_card("Control", analysis.control_score if analysis else None),
        _score_card("Fatiga", analysis.fatigue_score if analysis else None),
    ]

    charts = _build_analysis_chart_data(metrics, context_payload)
    recent_comparison = _build_recent_comparison_view(metrics, context_payload, linked_activity)
    technical = _build_technical_view(metrics_payload, context_payload, analysis)

    return {
        "state": {
            "status": status_value,
            "has_analysis": analysis is not None,
            "has_activity": linked_activity is not None,
            "is_error": status_value == "error",
            "is_pending": status_value in {"pending", "missing"},
            "message": _analysis_v2_state_message(status_value, linked_activity is not None, analysis.error_message if analysis else None),
        },
        "header": header,
        "conclusion": conclusion,
        "scores": scores,
        "positives": structured_output.get("key_positive_points") or [],
        "risks": structured_output.get("key_risk_points") or [],
        "recommendation": analysis.next_recommendation if analysis and analysis.next_recommendation else _empty_recommendation_copy(status_value, linked_activity is not None),
        "session_type_detected": structured_output.get("session_type_detected") or "-",
        "overall_assessment": structured_output.get("overall_assessment") or "-",
        "tags": structured_output.get("tags") or [],
        "charts": charts,
        "recent_comparison": recent_comparison,
        "technical": technical,
    }


def _analysis_v2_status_label(status_value: str) -> str:
    return {
        "completed": "Completo",
        "completed_with_warnings": "Completo con advertencias",
        "error": "Error en analisis",
        "pending": "Pendiente",
        "missing": "Sin analisis",
    }.get(status_value, status_value or "Sin analisis")


def _analysis_v2_status_class(status_value: str) -> str:
    return {
        "completed": "analysis-status-good",
        "completed_with_warnings": "analysis-status-warn",
        "error": "analysis-status-bad",
        "pending": "analysis-status-neutral",
        "missing": "analysis-status-neutral",
    }.get(status_value, "analysis-status-neutral")


def _analysis_v2_state_message(status_value: str, has_activity: bool, error_message: str | None) -> str:
    if status_value == "error":
        return error_message or "Hubo un error al generar el analisis."
    if not has_activity:
        return "No hay actividad vinculada. El analisis V2 se genera cuando una actividad queda asociada a la sesion."
    if status_value in {"pending", "missing"}:
        return "Analisis pendiente. La sesion todavia no tiene un analisis V2 listo para mostrar."
    if status_value == "completed_with_warnings":
        return "El analisis esta disponible, pero algunas partes se resolvieron con fallback o datos incompletos."
    return ""


def _empty_conclusion_copy(status_value: str) -> str:
    if status_value == "error":
        return "No se pudo completar el analisis automatico de esta sesion."
    if status_value in {"pending", "missing"}:
        return "Todavia no hay una conclusion disponible para esta sesion."
    return "La conclusion principal no esta disponible."


def _empty_summary_copy(status_value: str) -> str:
    if status_value == "error":
        return "Analisis V2 interrumpido por un error."
    if status_value in {"pending", "missing"}:
        return "Analisis pendiente o aun no generado."
    return "No hay resumen corto disponible."


def _empty_recommendation_copy(status_value: str, has_activity: bool) -> str:
    if not has_activity:
        return "Primero hace falta vincular una actividad real para poder analizar esta sesion."
    if status_value == "error":
        return "Reintentar el analisis una vez resuelto el error tecnico."
    return "Todavia no hay recomendacion disponible."


def _duration_minutes_label(value: int | None) -> str:
    if value is None:
        return "-"
    hours, minutes = divmod(int(value), 60)
    if hours and minutes:
        return f"{hours}:{minutes:02d} h"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def _distance_km_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f} km" if value >= 1 else f"{round(value * 1000)} m"


def _score_card(label: str, value: float | None) -> dict[str, Any]:
    if value is None:
        return {"label": label, "value": "-", "class": "score-card-neutral"}
    if value >= 80:
        score_class = "score-card-good"
    elif value >= 60:
        score_class = "score-card-warn"
    else:
        score_class = "score-card-bad"
    return {"label": label, "value": round(value), "class": score_class}


def _build_analysis_chart_data(metrics: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    laps = context_payload.get("activity_laps") or []
    hr_labels: list[str] = []
    hr_values: list[int] = []
    pace_labels: list[str] = []
    pace_values: list[float] = []

    for index, lap in enumerate(laps, start=1):
        label = lap.get("name") or lap.get("lap_type") or f"Lap {lap.get('index') or index}"
        avg_hr = lap.get("avg_hr")
        avg_pace_sec_km = lap.get("avg_pace_sec_km")
        if avg_hr is not None:
            hr_labels.append(label)
            hr_values.append(avg_hr)
        if avg_pace_sec_km is not None:
            pace_labels.append(label)
            pace_values.append(round(float(avg_pace_sec_km) / 60.0, 2))

    hr_zone_pct = (((metrics.get("heart_rate") or {}).get("estimated_pct_in_zones")) or {})
    zone_labels = list(hr_zone_pct.keys())
    zone_values = [hr_zone_pct[name] for name in zone_labels]

    return {
        "show_hr": len(hr_values) >= 2,
        "show_pace": len(pace_values) >= 2,
        "show_zones": any(value for value in zone_values),
        "hr": {"labels": hr_labels, "values": hr_values},
        "pace": {"labels": pace_labels, "values": pace_values},
        "zones": {"labels": zone_labels, "values": zone_values},
    }


def _build_recent_comparison_view(metrics: dict[str, Any], context_payload: dict[str, Any], linked_activity) -> dict[str, Any] | None:
    rows = context_payload.get("recent_similar_sessions") or []
    if not rows:
        return None

    current = {
        "duration_min": round((linked_activity.duration_sec or 0) / 60.0, 1) if linked_activity and linked_activity.duration_sec is not None else None,
        "distance_km": round((linked_activity.distance_m or 0) / 1000.0, 2) if linked_activity and linked_activity.distance_m is not None else None,
        "avg_hr": linked_activity.avg_hr if linked_activity else None,
        "avg_pace_min_km": round(float(linked_activity.avg_pace_sec_km) / 60.0, 2) if linked_activity and linked_activity.avg_pace_sec_km is not None else None,
    }

    table_rows = []
    for row in rows:
        table_rows.append(
            {
                "date": _format_iso_date(row.get("date")),
                "duration": _duration_seconds_compact(row.get("duration_sec")),
                "distance": _distance_meters_compact(row.get("distance_m")),
                "avg_hr": row.get("avg_hr") or "-",
                "avg_pace": _pace_seconds_compact(row.get("avg_pace_sec_km")),
                "title": row.get("title") or "-",
            }
        )

    recent_metrics = (metrics.get("comparisons") or {}).get("recent_similar") or {}
    averages = {
        "duration_vs_avg_pct": _signed_pct_label(recent_metrics.get("duration_vs_recent_avg_pct")),
        "distance_vs_avg_pct": _signed_pct_label(recent_metrics.get("distance_vs_recent_avg_pct")),
        "avg_hr_vs_avg": _signed_plain_label(recent_metrics.get("avg_hr_vs_recent_avg")),
        "avg_pace_vs_avg_sec_km": _signed_plain_label(recent_metrics.get("avg_pace_vs_recent_avg_sec_km"), suffix=" s/km"),
    }

    return {"rows": table_rows, "current": current, "averages": averages}


def _build_technical_view(metrics_payload: dict[str, Any], context_payload: dict[str, Any], analysis: SessionAnalysis | None) -> dict[str, Any]:
    laps = context_payload.get("activity_laps") or []
    lap_rows = [
        {
            "index": lap.get("index"),
            "name": lap.get("name") or lap.get("lap_type") or f"Lap {lap.get('index')}",
            "duration": _duration_seconds_compact(lap.get("duration_sec")),
            "distance": _distance_meters_compact(lap.get("distance_m")),
            "avg_hr": lap.get("avg_hr") or "-",
            "pace": _pace_seconds_compact(lap.get("avg_pace_sec_km")),
            "power": lap.get("avg_power") or "-",
            "cadence": round(lap.get("avg_cadence"), 1) if lap.get("avg_cadence") is not None else "-",
        }
        for lap in laps
    ]
    return {
        "metrics_pretty": json.dumps(metrics_payload.get("metrics", {}), indent=2, ensure_ascii=False) if metrics_payload else "{}",
        "llm_pretty": json.dumps((analysis.llm_json if analysis and analysis.llm_json else {}), indent=2, ensure_ascii=False),
        "lap_rows": lap_rows,
        "error_message": analysis.error_message if analysis else None,
    }


def _build_session_detail_view_model(planned_session, analysis_v2: SessionAnalysis | None) -> dict[str, Any]:
    linked_activity = (
        planned_session.activity_match.garmin_activity
        if planned_session.activity_match and planned_session.activity_match.garmin_activity
        else None
    )
    session_metrics = derive_session_metrics(planned_session)
    objective_duration_sec = (
        planned_session.expected_duration_min * 60
        if planned_session.expected_duration_min is not None
        else session_metrics.duration_sec
    )
    objective_distance_m = (
        int(round(planned_session.expected_distance_km * 1000))
        if planned_session.expected_distance_km is not None
        else session_metrics.distance_m
    )
    metrics_payload = analysis_v2.metrics_json if analysis_v2 and isinstance(analysis_v2.metrics_json, dict) else {}
    metrics = metrics_payload.get("metrics", {}) if isinstance(metrics_payload, dict) else {}
    block_rows = _extract_v2_step_rows(metrics)

    activity_match = planned_session.activity_match
    confidence_pct = (
        round(float(activity_match.match_confidence) * 100)
        if activity_match and activity_match.match_confidence is not None
        else None
    )
    activity_stats = [
        {"label": "Duracion", "value": _duration_seconds_compact(linked_activity.duration_sec) if linked_activity else "-"},
        {"label": "Distancia", "value": _distance_meters_compact(linked_activity.distance_m) if linked_activity else "-"},
        {"label": "FC promedio", "value": str(linked_activity.avg_hr) if linked_activity and linked_activity.avg_hr is not None else "-"},
        {"label": "Inicio", "value": linked_activity.start_time.strftime("%H:%M") if linked_activity and linked_activity.start_time else "-"},
    ]
    activity_meta = [
        {"label": "Vinculo", "value": label_for(MATCH_METHOD_LABELS, activity_match.match_method) if activity_match else "Sin vinculacion"},
        {"label": "Confianza", "value": f"{confidence_pct}%" if confidence_pct is not None else "-"},
    ]

    return {
        "header": {
            "title": session_metrics.title or planned_session.name,
            "sport_label": _sport_label(planned_session.sport_type),
            "duration_label": _duration_seconds_compact(objective_duration_sec),
            "distance_label": _distance_meters_compact(objective_distance_m),
            "session_type_label": label_for(STEP_TYPE_LABELS, None, "") if False else None,
        },
        "activity": {
            "linked": linked_activity is not None,
            "title": linked_activity.activity_name if linked_activity and linked_activity.activity_name else "Sin actividad vinculada",
            "url": f"/activities/{linked_activity.id}" if linked_activity else None,
            "subtitle": _sport_label(linked_activity.sport_type) if linked_activity and linked_activity.sport_type else "Esperando una actividad real para comparar.",
            "stats": activity_stats,
            "meta": activity_meta,
            "match_status_label": "Match confirmado" if activity_match else "Sin match confirmado",
            "match_badge_class": "status-badge-manual" if activity_match and activity_match.match_method == "manual" else "status-badge-garmin" if activity_match else "status-badge-empty",
        },
        "quick_compare": _build_session_quick_compare_view(
            planned_session=planned_session,
            linked_activity=linked_activity,
            analysis_v2=analysis_v2,
            metrics=metrics,
            objective_duration_sec=objective_duration_sec,
            objective_distance_m=objective_distance_m,
            block_rows=block_rows,
        ),
        "notes": {
            "description": planned_session.description_text,
            "target_notes": planned_session.target_notes,
        },
        "steps": {
            "has_steps": bool(build_session_display_blocks_for_session(planned_session)),
            "cards": _build_step_cards_view(planned_session, block_rows),
        },
        "latest_analysis": _build_latest_analysis_summary_view(planned_session, analysis_v2, linked_activity is not None),
    }


def _build_session_quick_compare_view(
    *,
    planned_session,
    linked_activity,
    analysis_v2: SessionAnalysis | None,
    metrics: dict[str, Any],
    objective_duration_sec: int | None,
    objective_distance_m: int | None,
    block_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    planned_vs_actual = metrics.get("planned_vs_actual", {}) if isinstance(metrics, dict) else {}
    lap_metrics = metrics.get("laps", {}) if isinstance(metrics, dict) else {}
    overall_score = _session_analysis_overall_score(analysis_v2)
    sport_matches = linked_activity is not None and _normalized_sport(linked_activity.sport_type) == _normalized_sport(planned_session.sport_type)

    duration_real = (
        _duration_seconds_compact(linked_activity.duration_sec)
        if linked_activity and linked_activity.duration_sec is not None
        else _v2_metric_actual_label(planned_vs_actual.get("duration"), "min")
    )
    distance_real = (
        _distance_meters_compact(linked_activity.distance_m)
        if linked_activity and linked_activity.distance_m is not None
        else _v2_metric_actual_label(planned_vs_actual.get("distance"), "km")
    )
    total_blocks = (
        int(lap_metrics.get("matched_count", 0)) + int(lap_metrics.get("missing_planned_steps", 0))
        if isinstance(lap_metrics, dict)
        else len(block_rows)
    )
    correct_blocks = sum(1 for row in block_rows if row.get("status_key") == "correct")

    return [
        {
            "label": "Duracion",
            "planned": _duration_seconds_compact(objective_duration_sec),
            "actual": duration_real,
        },
        {
            "label": "Distancia",
            "planned": _distance_meters_compact(objective_distance_m),
            "actual": distance_real,
        },
        {
            "label": "Deporte",
            "planned": _sport_label(planned_session.sport_type),
            "actual": "Correcto" if sport_matches else _sport_label(linked_activity.sport_type) if linked_activity else "-",
            "badge_class": "status-badge-garmin" if sport_matches else "status-badge-empty",
        },
        {
            "label": "Bloques",
            "planned": f"{total_blocks} planificados" if total_blocks else "-",
            "actual": f"{correct_blocks}/{total_blocks} correctos" if total_blocks else "-",
        },
        {
            "label": "Score",
            "planned": "General",
            "actual": f"{overall_score:.1f}" if overall_score is not None else "-",
            "badge_class": _score_badge_class(overall_score),
        },
    ]


def _build_latest_report_summary_view(latest_report, structured_summary: dict[str, Any], has_activity: bool) -> dict[str, Any]:
    """Compatibilidad temporal: la pantalla de sesion ya usa el resumen V2."""
    if latest_report is None:
        return {
            "exists": False,
            "title": "Último reporte",
            "empty_message": (
                "Todavia no hay un analisis generado para esta sesion."
                if has_activity
                else "Todavia no hay analisis porque la sesion no tiene una actividad vinculada."
            ),
            "show_analyze_cta": has_activity,
        }

    summary_text = latest_report.final_conclusion_text or latest_report.summary_text or "-"
    return {
        "exists": True,
        "title": "Resumen del ultimo analisis",
        "status_label": _session_step_status_label(latest_report.overall_status),
        "status_class": _session_step_status_class(latest_report.overall_status),
        "score_label": round(float(latest_report.overall_score), 1) if latest_report.overall_score is not None else "-",
        "reading": summary_text,
        "summary": latest_report.summary_text or "-",
        "recommendation": latest_report.recommendation_text or None,
        "url": f"/analysis/{latest_report.id}",
        "report_id": latest_report.id,
    }


def _build_step_cards_view(planned_session, block_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = build_session_display_blocks_for_session(planned_session)
    cards: list[dict[str, Any]] = []
    row_index = 0

    for display_index, block in enumerate(blocks, start=1):
        if getattr(block, "kind", None) == "repeat":
            nested_items = []
            for nested_index, step in enumerate(block.steps, start=1):
                row = block_rows[row_index] if row_index < len(block_rows) else None
                row_index += 1
                nested_items.append(_build_step_item_view(step, row, nested_index))
            cards.append(
                {
                    "kind": "repeat",
                    "title": f"{display_index}º Bloque",
                    "subtitle": f"Repetir {block.repeat_count} veces",
                    "items": nested_items,
                }
            )
            continue

        row = block_rows[row_index] if row_index < len(block_rows) else None
        row_index += 1
        cards.append(
            {
                "kind": "simple",
                "title": f"{display_index}º Bloque",
                "item": _build_step_item_view(block, row, None),
            }
        )

    return cards


def _build_step_item_view(step: Any, row: dict[str, Any] | None, nested_index: int | None) -> dict[str, Any]:
    summary_parts = []
    duration_label = _duration_seconds_compact(getattr(step, "duration_sec", None))
    distance_label = _distance_meters_compact(getattr(step, "distance_m", None))
    if duration_label != "-":
        summary_parts.append(duration_label)
    if distance_label != "-":
        summary_parts.append(distance_label)

    intensity_parts = []
    target_type = getattr(step, "target_type", None)
    if target_type:
        intensity_parts.append(label_for(INTENSITY_TARGET_LABELS, target_type))
    for zone_attr in ("target_hr_zone", "target_pace_zone", "target_power_zone", "target_rpe_zone"):
        zone_value = getattr(step, zone_attr, None)
        if zone_value:
            intensity_parts.append(zone_value)
            break
    if getattr(step, "target_hr_min", None) is not None or getattr(step, "target_hr_max", None) is not None:
        intensity_parts.append(f"HR {getattr(step, 'target_hr_min', None) or '-'}-{getattr(step, 'target_hr_max', None) or '-'}")
    elif getattr(step, "target_pace_min_sec_km", None) is not None or getattr(step, "target_pace_max_sec_km", None) is not None:
        intensity_parts.append(
            f"Ritmo {_pace_seconds_compact(getattr(step, 'target_pace_min_sec_km', None))} a {_pace_seconds_compact(getattr(step, 'target_pace_max_sec_km', None))}"
        )
    elif getattr(step, "target_power_min", None) is not None or getattr(step, "target_power_max", None) is not None:
        intensity_parts.append(f"Potencia {getattr(step, 'target_power_min', None) or '-'}-{getattr(step, 'target_power_max', None) or '-'} w")

    row_status = row.get("status") if row else None
    comment = row.get("comment") if row else None
    actual_text = row.get("actual") if row else None
    return {
        "label": f"Paso {nested_index}" if nested_index else label_for(STEP_TYPE_LABELS, getattr(step, "step_type", None), "Bloque"),
        "summary": " | ".join(summary_parts) if summary_parts else "-",
        "intensity": " | ".join(intensity_parts) if intensity_parts else None,
        "notes": getattr(step, "target_notes", None),
        "status_label": row.get("status_label") if row and row.get("status_label") else _session_step_status_label(row_status),
        "status_class": row.get("status_class") if row and row.get("status_class") else _session_step_status_class(row_status),
        "actual_text": actual_text if actual_text and actual_text != "Sin lap correspondiente" else None,
        "comment": comment,
        "missing_match": actual_text == "Sin lap correspondiente" if row else False,
        "status_key": row.get("status_key") if row else None,
    }


def _session_step_status_label(value: str | None) -> str:
    return {
        "correct": "Correcto",
        "partial": "Desviado",
        "review": "Revisar",
        "failed": "No completado",
        "not_completed": "No completado",
        "skipped": "Sin match",
        None: "Sin match",
    }.get(value, "Sin match")


def _session_step_status_class(value: str | None) -> str:
    return {
        "correct": "status-badge-garmin",
        "partial": "status-badge-active",
        "review": "status-badge-empty",
        "failed": "status-badge-manual",
        "not_completed": "status-badge-manual",
        "skipped": "status-badge-empty",
        None: "status-badge-empty",
    }.get(value, "status-badge-empty")


def _score_badge_class(value: float | None) -> str:
    if value is None:
        return "status-badge-empty"
    if value >= 85:
        return "status-badge-garmin"
    if value >= 60:
        return "status-badge-active"
    return "status-badge-manual"


def _build_latest_analysis_summary_view(planned_session, analysis_v2: SessionAnalysis | None, has_activity: bool) -> dict[str, Any]:
    if analysis_v2 is None:
        return {
            "exists": False,
            "title": "Ultimo reporte",
            "empty_message": (
                "Todavia no hay un analisis generado para esta sesion."
                if has_activity
                else "Todavia no hay analisis porque la sesion no tiene una actividad vinculada."
            ),
            "show_analyze_cta": has_activity,
            "analyze_url": f"/planned_sessions/{planned_session.id}/analysis/re-run",
        }

    score_value = _session_analysis_overall_score(analysis_v2)
    return {
        "exists": True,
        "title": "Resumen del ultimo analisis",
        "status_label": _analysis_v2_status_label(analysis_v2.status),
        "status_class": _analysis_v2_status_class(analysis_v2.status),
        "score_label": round(float(score_value), 1) if score_value is not None else "-",
        "reading": analysis_v2.coach_conclusion or _empty_conclusion_copy(analysis_v2.status),
        "summary": analysis_v2.summary_short or _empty_summary_copy(analysis_v2.status),
        "recommendation": analysis_v2.next_recommendation or None,
        "url": f"/planned_sessions/{planned_session.id}/analysis",
        "analysis_id": analysis_v2.id,
    }


def _extract_v2_step_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    lap_metrics = metrics.get("laps", {}) if isinstance(metrics, dict) else {}
    pairs = lap_metrics.get("pairs", []) if isinstance(lap_metrics, dict) else []
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        target_evaluation = pair.get("target_evaluation") if isinstance(pair, dict) else None
        status_key, status_label, status_class = _v2_step_status_display(pair, target_evaluation)
        rows.append(
            {
                "status": status_key,
                "status_key": status_key,
                "status_label": status_label,
                "status_class": status_class,
                "actual": _v2_pair_actual_summary(pair),
                "comment": _v2_pair_comment(pair, target_evaluation),
            }
        )
    return rows


def _session_analysis_overall_score(analysis: SessionAnalysis | None) -> float | None:
    if analysis is None:
        return None
    values = [
        value
        for value in (
            analysis.compliance_score,
            analysis.execution_score,
            analysis.control_score,
            analysis.fatigue_score,
        )
        if value is not None
    ]
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 1)


def _v2_metric_actual_label(payload: Any, unit: str) -> str:
    if not isinstance(payload, dict):
        return "-"
    value = payload.get("actual")
    if value is None:
        return "-"
    if unit == "km":
        return _distance_km_label(float(value))
    if unit == "min":
        return _duration_minutes_label(int(round(float(value))))
    return str(value)


def _normalized_sport(value: str | None) -> str:
    return (value or "").strip().lower()


def _v2_step_status_display(pair: dict[str, Any], target_evaluation: dict[str, Any] | None) -> tuple[str, str, str]:
    if target_evaluation and target_evaluation.get("within_range") is True:
        return ("correct", "Correcto", "status-badge-garmin")
    if target_evaluation and target_evaluation.get("status") in {"above_range", "below_range"}:
        return ("partial", "Desviado", "status-badge-active")

    duration_delta_pct = pair.get("duration_delta_pct")
    distance_delta_pct = pair.get("distance_delta_pct")
    close_duration = duration_delta_pct is None or abs(float(duration_delta_pct)) <= 15
    close_distance = distance_delta_pct is None or abs(float(distance_delta_pct)) <= 15
    if close_duration and close_distance:
        return ("correct", "Correcto", "status-badge-garmin")
    return ("partial", "Desviado", "status-badge-active")


def _v2_pair_actual_summary(pair: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if pair.get("actual_duration_sec") is not None:
        parts.append(_duration_seconds_compact(pair.get("actual_duration_sec")))
    if pair.get("actual_distance_m") is not None:
        parts.append(_distance_meters_compact(pair.get("actual_distance_m")))
    if pair.get("avg_hr") is not None:
        parts.append(f"avg HR {pair.get('avg_hr')}")
    if pair.get("avg_pace_sec_km") is not None:
        parts.append(f"pace {_pace_seconds_compact(pair.get('avg_pace_sec_km'))}")
    if pair.get("avg_power") is not None:
        parts.append(f"avg power {pair.get('avg_power')}")
    return " | ".join(parts) if parts else None


def _v2_pair_comment(pair: dict[str, Any], target_evaluation: dict[str, Any] | None) -> str | None:
    if target_evaluation and target_evaluation.get("status") == "above_range":
        return "La intensidad real quedo por encima del objetivo del bloque."
    if target_evaluation and target_evaluation.get("status") == "below_range":
        return "La intensidad real quedo por debajo del objetivo del bloque."

    duration_delta_pct = pair.get("duration_delta_pct")
    distance_delta_pct = pair.get("distance_delta_pct")
    if duration_delta_pct is not None and abs(float(duration_delta_pct)) > 20:
        return "La duracion real se desvio bastante respecto de lo planificado."
    if distance_delta_pct is not None and abs(float(distance_delta_pct)) > 20:
        return "La distancia real del lap quedo lejos de la referencia planificada."
    return None


def _format_iso_date(value: Any) -> str:
    if not value:
        return "-"
    try:
        return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _sport_label(value: str | None) -> str:
    if not value:
        return "-"
    return SPORT_LABELS.get(value, value.replace("_", " ").title())


def _duration_seconds_compact(value: Any) -> str:
    if value is None:
        return "-"
    total_seconds = int(float(value))
    total_minutes = round(total_seconds / 60.0)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d} h"
    return f"{minutes} min"


def _distance_meters_compact(value: Any) -> str:
    if value is None:
        return "-"
    numeric = float(value)
    if numeric >= 1000:
        return f"{numeric / 1000.0:.2f} km"
    return f"{round(numeric)} m"


def _pace_seconds_compact(value: Any) -> str:
    if value is None:
        return "-"
    total_seconds = int(round(float(value)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d} min/km"


def _signed_pct_label(value: Any) -> str:
    if value is None:
        return "-"
    numeric = float(value)
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.1f}%"


def _signed_plain_label(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    numeric = float(value)
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.1f}{suffix}"


@router.post("/quick")
def create_quick_session_endpoint(
    mode: str = Form(default="simple"),
    planned_session_id: str | None = Form(default=None),
    training_day_id: str | None = Form(default=None),
    training_plan_id: str | None = Form(default=None),
    planned_day_date: str | None = Form(default=None),
    simple_sport_type: str | None = Form(default=None),
    simple_name: str | None = Form(default=None),
    simple_expected_duration_min: str | None = Form(default=None),
    simple_expected_distance_km: str | None = Form(default=None),
    simple_target_type: str | None = Form(default=None),
    simple_target_hr_zone: str | None = Form(default=None),
    simple_target_pace_zone: str | None = Form(default=None),
    simple_target_power_zone: str | None = Form(default=None),
    simple_target_rpe_zone: str | None = Form(default=None),
    simple_target_notes: str | None = Form(default=None),
    builder_blocks_json: str | None = Form(default=None),
    simple_group_mode: str | None = Form(default="existing"),
    simple_session_group_id: str | None = Form(default=None),
    simple_new_group_name: str | None = Form(default=None),
    simple_new_group_type: str | None = Form(default=None),
    simple_new_group_notes: str | None = Form(default=None),
    raw_text: str | None = Form(default=None),
    builder_raw_text: str | None = Form(default=None),
    text_sport_type_override: str | None = Form(default=None),
    text_group_mode: str | None = Form(default="existing"),
    text_session_group_id: str | None = Form(default=None),
    text_new_group_name: str | None = Form(default=None),
    text_new_group_type: str | None = Form(default=None),
    text_new_group_notes: str | None = Form(default=None),
    builder_sport_type_override: str | None = Form(default=None),
    advanced_name: str | None = Form(default=None),
    advanced_is_key_session: bool = Form(default=False),
    advanced_expected_duration_hhmm: str | None = Form(default=None),
    advanced_expected_distance_value: str | None = Form(default=None),
    advanced_expected_distance_unit: str | None = Form(default="km"),
    advanced_target_type: str | None = Form(default=None),
    advanced_target_hr_zone: str | None = Form(default=None),
    advanced_target_pace_zone: str | None = Form(default=None),
    advanced_target_power_zone: str | None = Form(default=None),
    advanced_target_rpe_zone: str | None = Form(default=None),
    advanced_target_notes: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
    return_month: str | None = Form(default=None),
    return_selected_date: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    normalized_mode = (mode or "simple").strip().lower()
    try:
        editing_session = None
        resolved_planned_session_id = _parse_int_field(planned_session_id, "La sesion seleccionada no es valida.")
        if resolved_planned_session_id is not None:
            editing_session = get_planned_session(db, resolved_planned_session_id)
            if editing_session is None:
                raise ValueError("La sesion seleccionada no existe.")

        effective_training_day_id = _resolve_or_create_training_day_id(
            db,
            training_day_id=training_day_id or (str(editing_session.training_day_id) if editing_session else None),
            training_plan_id=training_plan_id,
            planned_day_date=planned_day_date,
        )
        if normalized_mode == "simple":
            session_group_id = _resolve_session_group_id(
                db,
                training_day_id=effective_training_day_id,
                group_mode=simple_group_mode,
                session_group_id=simple_session_group_id,
                new_group_name=simple_new_group_name,
                new_group_type=simple_new_group_type,
                new_group_notes=simple_new_group_notes,
            )
        elif normalized_mode == "text":
            session_group_id = _resolve_session_group_id(
                db,
                training_day_id=effective_training_day_id,
                group_mode=text_group_mode,
                session_group_id=text_session_group_id,
                new_group_name=text_new_group_name,
                new_group_type=text_new_group_type,
                new_group_notes=text_new_group_notes,
            )
        else:
            session_group_id = None
        advanced_data = SessionAdvancedData(
            name=(advanced_name or "").strip() or None,
            session_group_id=session_group_id,
            is_key_session=advanced_is_key_session,
            expected_duration_min=_parse_duration_hhmm(advanced_expected_duration_hhmm),
            expected_distance_km=_distance_to_km(advanced_expected_distance_value, advanced_expected_distance_unit),
            target_type=advanced_target_type or None,
            target_hr_zone=advanced_target_hr_zone or None,
            target_pace_zone=advanced_target_pace_zone or None,
            target_power_zone=advanced_target_power_zone or None,
            target_rpe_zone=advanced_target_rpe_zone or None,
            target_notes=advanced_target_notes or None,
        )

        mode_sport = {
            "simple": simple_sport_type or None,
            "text": text_sport_type_override or None,
            "builder": builder_sport_type_override or None,
        }.get(normalized_mode)
        mode_variant = {
            "simple": None,
            "text": None,
            "builder": None,
        }.get(normalized_mode)

        raw_session_text = (builder_raw_text if normalized_mode == "builder" else raw_text) or None
        if editing_session is not None:
            result = _update_session_from_quick_mode(
                db,
                planned_session=editing_session,
                training_day_id=effective_training_day_id,
                mode=normalized_mode,
                sport_type=mode_sport,
                discipline_variant=mode_variant,
                name=(simple_name or "").strip() or None,
                expected_duration_min=_parse_duration_hhmm(simple_expected_duration_min),
                expected_distance_km=_parse_float_field(simple_expected_distance_km, "La distancia simple debe ser un numero."),
                target_type=simple_target_type or None,
                target_hr_zone=simple_target_hr_zone or None,
                target_pace_zone=simple_target_pace_zone or None,
                target_power_zone=simple_target_power_zone or None,
                target_rpe_zone=simple_target_rpe_zone or None,
                target_notes=simple_target_notes or None,
                raw_text=raw_session_text,
                builder_blocks_json=builder_blocks_json,
                is_key_session=advanced_is_key_session,
                advanced_data=advanced_data,
            )
        else:
            result = create_session_from_quick_mode(
                db,
                training_day_id=effective_training_day_id,
                mode=normalized_mode,
                sport_type=mode_sport,
                discipline_variant=mode_variant,
                name=(simple_name or "").strip() or None,
                description_text=None,
                expected_duration_min=_parse_duration_hhmm(simple_expected_duration_min),
                expected_distance_km=_parse_float_field(simple_expected_distance_km, "La distancia simple debe ser un numero."),
                target_type=simple_target_type or None,
                target_hr_zone=simple_target_hr_zone or None,
                target_pace_zone=simple_target_pace_zone or None,
                target_power_zone=simple_target_power_zone or None,
                target_rpe_zone=simple_target_rpe_zone or None,
                target_notes=simple_target_notes or None,
                raw_text=raw_session_text,
                is_key_session=advanced_is_key_session,
                advanced_data=advanced_data,
            )
        created_training_day = get_training_day(db, effective_training_day_id)
        normalized_return_to = (return_to or "").strip().lower()
        if normalized_return_to == "calendar" and created_training_day is not None:
            calendar_month = return_month or created_training_day.day_date.strftime("%Y-%m")
            selected_day = return_selected_date or created_training_day.day_date.isoformat()
            return RedirectResponse(
                url=(
                    f"/training_plans/{created_training_day.training_plan.id}/calendar"
                    f"?month={quote(calendar_month)}&selected_date={quote(selected_day)}&status={quote('Sesion creada')}"
                ),
                status_code=303,
            )
        if normalized_return_to == "plan" and created_training_day is not None:
            return RedirectResponse(
                url=f"/training_plans/{created_training_day.training_plan.id}#training-day-{created_training_day.id}",
                status_code=303,
            )
        if editing_session is not None:
            return RedirectResponse(url=f"/planned_sessions/{result.planned_session.id}", status_code=303)
        return RedirectResponse(url=f"/planned_sessions/{result.planned_session.id}", status_code=303)
    except ValueError as exc:
        redirect_target = _quick_session_redirect_target(
            planned_session_id=planned_session_id,
            training_day_id=training_day_id,
            training_plan_id=training_plan_id,
            planned_day_date=planned_day_date,
            mode=normalized_mode,
            error=str(exc),
            return_to=return_to,
            return_month=return_month,
            return_selected_date=return_selected_date,
        )
        return RedirectResponse(
            url=redirect_target,
            status_code=303,
        )


@router.post("/parse")
def create_session_from_text_endpoint(
    training_day_id: int = Form(...),
    raw_text: str = Form(...),
    sport_type_override: str | None = Form(default=None),
    discipline_variant_override: str | None = Form(default=None),
    is_key_session: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        result = create_session_from_natural_language(
            db,
            training_day_id=training_day_id,
            raw_text=raw_text,
            sport_type_override=sport_type_override or None,
            discipline_variant_override=discipline_variant_override or None,
            is_key_session=is_key_session,
        )
        status_message = (
            f"Sesion creada desde texto. Pasos generados: {result.created_steps}. "
            f"Nivel de interpretacion: {result.parse_mode}."
        )
        return RedirectResponse(
            url=f"/planned_sessions/{result.planned_session.id}?ui_status={quote(status_message)}",
            status_code=303,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/planned_sessions/quick?training_day_id={training_day_id}&mode=text&error={quote(str(exc))}#text",
            status_code=303,
        )


@router.get("/{planned_session_id}/edit", response_class=HTMLResponse)
def edit_planned_session_page(planned_session_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    mode = _infer_quick_mode_for_planned_session(planned_session)
    return RedirectResponse(url=f"/planned_sessions/quick?planned_session_id={planned_session.id}&mode={quote(mode)}#{quote(mode)}", status_code=303)


@router.post("", response_model=PlannedSessionRead, status_code=status.HTTP_201_CREATED)
def create_planned_session_endpoint(
    planned_session_in: PlannedSessionCreate,
    db: Session = Depends(get_db),
) -> PlannedSessionRead:
    try:
        return create_planned_session(db, planned_session_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{planned_session_id}", response_model=PlannedSessionRead)
def update_planned_session_endpoint(
    planned_session_id: int,
    planned_session_in: PlannedSessionUpdate,
    db: Session = Depends(get_db),
) -> PlannedSessionRead:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    try:
        return update_planned_session(db, planned_session, planned_session_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{planned_session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_planned_session_endpoint(planned_session_id: int, db: Session = Depends(get_db)) -> Response:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    delete_planned_session(db, planned_session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _parse_duration_hhmm(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lower_value = normalized.lower().replace(" ", "")

    hhmm_match = lower_value.split(":")
    if len(hhmm_match) == 2:
        try:
            hours = int(hhmm_match[0])
            minutes = int(hhmm_match[1])
        except ValueError as exc:
            raise ValueError("La duracion avanzada no tiene un formato valido.") from exc
        if hours < 0 or minutes < 0 or minutes > 59:
            raise ValueError("La duracion avanzada no tiene un formato valido.")
        return hours * 60 + minutes

    compact_hours_minutes = re.fullmatch(r"(\d+)h(\d{1,2})", lower_value)
    if compact_hours_minutes:
        hours = int(compact_hours_minutes.group(1))
        minutes = int(compact_hours_minutes.group(2))
        if minutes > 59:
            raise ValueError("La duracion avanzada no tiene un formato valido.")
        return hours * 60 + minutes

    hours_only = re.fullmatch(r"(\d+)h(?:s)?", lower_value)
    if hours_only:
        return int(hours_only.group(1)) * 60

    minutes_text = re.fullmatch(r"(\d+)(?:min|m)", lower_value)
    if minutes_text:
        return int(minutes_text.group(1))

    plain_number = re.fullmatch(r"\d+", lower_value)
    if plain_number:
        total_minutes = int(lower_value)
        return total_minutes

    raise ValueError("La duracion avanzada no tiene un formato valido.")


def _parse_planned_start_time(value: str | None) -> time | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        hour_str, minute_str = normalized.split(":")
        return time(hour=int(hour_str), minute=int(minute_str))
    except (TypeError, ValueError) as exc:
        raise ValueError("La hora prevista no tiene un formato valido.") from exc


def _distance_to_km(value: str | float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            numeric_value = float(normalized)
        except ValueError as exc:
            raise ValueError("La distancia esperada debe ser un numero.") from exc
    else:
        numeric_value = value
    return numeric_value / 1000 if unit == "m" else numeric_value


def _parse_int_field(value: str | None, message: str) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(message) from exc


def _parse_float_field(value: str | None, message: str) -> float | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError as exc:
        raise ValueError(message) from exc


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _resolve_session_group_id(
    db: Session,
    *,
    training_day_id: int,
    group_mode: str | None,
    session_group_id: str | None,
    new_group_name: str | None,
    new_group_type: str | None,
    new_group_notes: str | None,
) -> int | None:
    normalized_mode = (group_mode or "existing").strip().lower()
    if normalized_mode == "new":
        group = create_inline_group(
            db,
            training_day_id=training_day_id,
            name=new_group_name or "",
            group_type=new_group_type or None,
            notes=new_group_notes or None,
        )
        return group.id
    return _parse_int_field(session_group_id, "El grupo seleccionado no es valido.")


def _resolve_or_create_training_day_id(
    db: Session,
    *,
    training_day_id: str | None,
    training_plan_id: str | None,
    planned_day_date: str | None,
) -> int:
    resolved_training_day_id = _parse_int_field(training_day_id, "El dia seleccionado no es valido.")
    if resolved_training_day_id is not None:
        training_day = get_training_day(db, resolved_training_day_id)
        if training_day is None:
            raise ValueError("El dia seleccionado no existe.")
        return training_day.id

    resolved_training_plan_id = _parse_int_field(training_plan_id, "El plan seleccionado no es valido.")
    if resolved_training_plan_id is None:
        raise ValueError("Falta el plan para crear la sesion.")
    if not planned_day_date or not planned_day_date.strip():
        raise ValueError("Elegi una fecha para crear la sesion.")
    try:
        parsed_day_date = date.fromisoformat(planned_day_date.strip())
    except ValueError as exc:
        raise ValueError("La fecha elegida no es valida.") from exc

    existing_day = get_training_day_by_plan_and_date(db, resolved_training_plan_id, parsed_day_date)
    if existing_day is not None:
        return existing_day.id

    training_day = create_training_day(
        db,
        TrainingDayCreate(
            training_plan_id=resolved_training_plan_id,
            day_date=parsed_day_date,
            day_notes=None,
            day_type=None,
        ),
    )
    return training_day.id


def _quick_session_redirect_target(
    *,
    planned_session_id: str | None = None,
    training_day_id: str | None,
    training_plan_id: str | None,
    planned_day_date: str | None,
    mode: str,
    error: str,
    return_to: str | None = None,
    return_month: str | None = None,
    return_selected_date: str | None = None,
) -> str:
    query_parts: list[str] = [f"mode={quote(mode)}", f"error={quote(error)}"]
    normalized_planned_session_id = (planned_session_id or "").strip()
    normalized_training_day_id = (training_day_id or "").strip()
    normalized_training_plan_id = (training_plan_id or "").strip()
    normalized_day_date = (planned_day_date or "").strip()

    if normalized_planned_session_id:
        query_parts.append(f"planned_session_id={quote(normalized_planned_session_id)}")
    if normalized_training_day_id:
        query_parts.append(f"training_day_id={quote(normalized_training_day_id)}")
    if normalized_training_plan_id:
        query_parts.append(f"training_plan_id={quote(normalized_training_plan_id)}")
    if normalized_day_date:
        query_parts.append(f"day_date={quote(normalized_day_date)}")
    normalized_return_to = (return_to or "").strip()
    normalized_return_month = (return_month or "").strip()
    normalized_return_selected_date = (return_selected_date or "").strip()
    if normalized_return_to:
        query_parts.append(f"return_to={quote(normalized_return_to)}")
    if normalized_return_month:
        query_parts.append(f"month={quote(normalized_return_month)}")
    if normalized_return_selected_date:
        query_parts.append(f"selected_date={quote(normalized_return_selected_date)}")
    return f"/planned_sessions/quick?{'&'.join(query_parts)}#{quote(mode)}"


def _infer_quick_mode_for_planned_session(planned_session) -> str:
    if planned_session is None:
        return "simple"
    if planned_session.planned_session_steps:
        return "builder"
    if planned_session.description_text:
        return "text"
    return "simple"


def _build_initial_quick_data(planned_session, initial_mode: str) -> dict:
    display_blocks = build_session_display_blocks(list(planned_session.planned_session_steps or []))
    return {
        "id": planned_session.id,
        "mode": initial_mode,
        "simple": {
            "sportType": planned_session.sport_type or "",
            "name": planned_session.name or "",
            "expectedDuration": _minutes_to_hhmm(planned_session.expected_duration_min),
            "expectedDistance": _float_to_string(planned_session.expected_distance_km),
            "targetType": planned_session.target_type or "",
            "targetHrZone": planned_session.target_hr_zone or "",
            "targetPaceZone": planned_session.target_pace_zone or "",
            "targetPowerZone": planned_session.target_power_zone or "",
            "targetRpeZone": planned_session.target_rpe_zone or "",
            "targetNotes": planned_session.target_notes or "",
            "sessionGroupId": planned_session.session_group_id or "",
        },
        "text": {
            "rawText": planned_session.description_text or "",
            "sportType": planned_session.sport_type or "",
            "sessionGroupId": planned_session.session_group_id or "",
        },
        "advanced": {
            "name": planned_session.name or "",
            "expectedDuration": _minutes_to_hhmm(planned_session.expected_duration_min),
            "expectedDistance": _float_to_string(planned_session.expected_distance_km),
            "targetType": planned_session.target_type or "",
            "targetHrZone": planned_session.target_hr_zone or "",
            "targetPaceZone": planned_session.target_pace_zone or "",
            "targetPowerZone": planned_session.target_power_zone or "",
            "targetRpeZone": planned_session.target_rpe_zone or "",
            "targetNotes": planned_session.target_notes or "",
            "isKeySession": planned_session.is_key_session,
        },
        "builder": {
            "sportType": planned_session.sport_type or "running",
            "rawText": planned_session.description_text or "",
            "blocks": [_display_block_to_builder_data(block, planned_session.target_type) for block in display_blocks],
        },
    }


def _display_block_to_builder_data(block, fallback_target_type: str | None = None) -> dict:
    if block.kind == "repeat":
        return {
            "kind": "repeat",
            "repeatCount": block.repeat_count,
            "steps": [_simple_block_to_builder_data(step, fallback_target_type) for step in block.steps],
        }
    return _simple_block_to_builder_data(block, fallback_target_type)


def _simple_block_to_builder_data(block, fallback_target_type: str | None = None) -> dict:
    value, unit = _measurement_to_builder_fields(block.duration_sec, block.distance_m)
    target_type = block.target_type or _infer_target_type_from_block(block, fallback_target_type)
    target_zone, custom_min, custom_max = _builder_target_fields_from_block(block, target_type)
    return {
        "kind": "simple",
        "value": value,
        "unit": unit,
        "targetType": target_type or "",
        "targetZone": target_zone or "",
        "customMin": custom_min or "",
        "customMax": custom_max or "",
        "stepType": block.step_type or "",
    }


def _measurement_to_builder_fields(duration_sec: int | None, distance_m: int | None) -> tuple[str, str]:
    if duration_sec:
        if duration_sec % 3600 == 0:
            return str(int(duration_sec / 3600)), "h"
        if duration_sec % 60 == 0:
            return str(int(duration_sec / 60)), "min"
        return str(int(duration_sec)), "seg"
    if distance_m:
        if distance_m % 1000 == 0:
            return str(distance_m // 1000), "km"
        return str(int(distance_m)), "m"
    return "", "min"


def _infer_target_type_from_block(block, fallback_target_type: str | None = None) -> str | None:
    if block.target_hr_zone or block.target_hr_min or block.target_hr_max:
        return "hr"
    if block.target_pace_zone or block.target_pace_min_sec_km or block.target_pace_max_sec_km:
        return "pace"
    if block.target_power_zone or block.target_power_min or block.target_power_max:
        return "power"
    if block.target_rpe_zone:
        return "rpe"
    if (block.target_notes or "").strip().upper() in {"Z1", "Z2", "Z3", "Z4", "Z5"}:
        return fallback_target_type
    return fallback_target_type


def _builder_target_fields_from_block(block, target_type: str | None) -> tuple[str | None, str | None, str | None]:
    if target_type == "hr":
        if block.target_hr_zone:
            return block.target_hr_zone, None, None
        if block.target_hr_min is not None or block.target_hr_max is not None:
            return "__custom__", _float_to_string(block.target_hr_min), _float_to_string(block.target_hr_max)
    if target_type == "pace":
        if block.target_pace_zone:
            return block.target_pace_zone, None, None
        if block.target_pace_min_sec_km is not None or block.target_pace_max_sec_km is not None:
            return "__custom__", _seconds_to_pace(block.target_pace_min_sec_km), _seconds_to_pace(block.target_pace_max_sec_km)
    if target_type == "power":
        if block.target_power_zone:
            return block.target_power_zone, None, None
        if block.target_power_min is not None or block.target_power_max is not None:
            return "__custom__", _float_to_string(block.target_power_min), _float_to_string(block.target_power_max)
    if target_type == "rpe" and block.target_rpe_zone:
        return block.target_rpe_zone, None, None
    if (block.target_notes or "").strip().upper() in {"Z1", "Z2", "Z3", "Z4", "Z5"}:
        return (block.target_notes or "").strip().upper(), None, None
    return None, None, None


def _seconds_to_pace(value: int | None) -> str | None:
    if value is None:
        return None
    minutes = value // 60
    seconds = value % 60
    return f"{minutes}:{seconds:02d}"


def _minutes_to_hhmm(value: int | None) -> str:
    if value is None:
        return ""
    hours = value // 60
    minutes = value % 60
    return f"{hours}:{minutes:02d}"


def _float_to_string(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _update_session_from_quick_mode(
    db: Session,
    *,
    planned_session,
    training_day_id: int,
    mode: str,
    sport_type: str | None = None,
    discipline_variant: str | None = None,
    name: str | None = None,
    expected_duration_min: int | None = None,
    expected_distance_km: float | None = None,
    target_type: str | None = None,
    target_hr_zone: str | None = None,
    target_pace_zone: str | None = None,
    target_power_zone: str | None = None,
    target_rpe_zone: str | None = None,
    target_notes: str | None = None,
    raw_text: str | None = None,
    builder_blocks_json: str | None = None,
    is_key_session: bool = False,
    advanced_data: SessionAdvancedData | None = None,
):
    advanced = advanced_data or SessionAdvancedData()
    normalized_mode = mode.strip().lower()

    if normalized_mode == "simple":
        parse_source = " ".join(part.strip() for part in ((name or ""), (raw_text or "")) if part and part.strip())
        parsed = parse_session_text(parse_source, fallback_sport_type=sport_type) if parse_source else None
        updated_session = update_planned_session(
            db,
            planned_session,
            PlannedSessionUpdate(
                training_day_id=training_day_id,
                sport_type=sport_type or (parsed.sport_type if parsed else planned_session.sport_type),
                discipline_variant=discipline_variant or (parsed.discipline_variant if parsed else planned_session.discipline_variant),
                name=advanced.name or name or planned_session.name,
                description_text=raw_text or planned_session.description_text,
                session_type=(parsed.session_type if parsed else planned_session.session_type) or advanced.session_type,
                session_group_id=advanced.session_group_id,
                expected_duration_min=expected_duration_min if expected_duration_min is not None else (parsed.expected_duration_min if parsed else advanced.expected_duration_min),
                expected_distance_km=expected_distance_km if expected_distance_km is not None else (parsed.expected_distance_km if parsed else advanced.expected_distance_km),
                expected_elevation_gain_m=advanced.expected_elevation_gain_m,
                target_type=target_type or advanced.target_type,
                target_hr_zone=target_hr_zone or advanced.target_hr_zone,
                target_pace_zone=target_pace_zone or advanced.target_pace_zone,
                target_power_zone=target_power_zone or advanced.target_power_zone,
                target_rpe_zone=target_rpe_zone or advanced.target_rpe_zone,
                target_notes=target_notes or advanced.target_notes,
                is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
            ),
        )
        replace_steps_for_session(db, updated_session, _build_default_steps_for_updated_session(updated_session))
        return type("QuickResult", (), {"planned_session": updated_session})

    if normalized_mode == "text":
        if not raw_text or not raw_text.strip():
            raise ValueError("Escribi la sesion antes de guardar.")
        parsed = parse_session_text(raw_text, fallback_sport_type=sport_type)
        updated_session = update_planned_session(
            db,
            planned_session,
            PlannedSessionUpdate(
                training_day_id=training_day_id,
                sport_type=sport_type or parsed.sport_type or planned_session.sport_type,
                discipline_variant=discipline_variant or parsed.discipline_variant or planned_session.discipline_variant,
                name=advanced.name or parsed.name or planned_session.name,
                description_text=raw_text,
                session_type=parsed.session_type or advanced.session_type or planned_session.session_type,
                session_group_id=advanced.session_group_id,
                expected_duration_min=parsed.expected_duration_min if parsed.expected_duration_min is not None else advanced.expected_duration_min,
                expected_distance_km=parsed.expected_distance_km if parsed.expected_distance_km is not None else advanced.expected_distance_km,
                expected_elevation_gain_m=advanced.expected_elevation_gain_m,
                target_type=advanced.target_type,
                target_hr_zone=parsed.target_hr_zone or advanced.target_hr_zone,
                target_pace_zone=advanced.target_pace_zone,
                target_power_zone=parsed.target_power_zone or advanced.target_power_zone,
                target_rpe_zone=advanced.target_rpe_zone,
                target_notes=parsed.target_notes or advanced.target_notes,
                is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
            ),
        )
        replace_steps_for_session(db, updated_session, _build_parsed_steps_for_updated_session(updated_session, parsed))
        return type("QuickResult", (), {"planned_session": updated_session})

    if normalized_mode == "builder":
        if not raw_text or not raw_text.strip():
            raise ValueError("Arma al menos un bloque antes de guardar.")
        parsed = parse_session_text(raw_text, fallback_sport_type=sport_type)
        updated_session = update_planned_session(
            db,
            planned_session,
            PlannedSessionUpdate(
                training_day_id=training_day_id,
                sport_type=sport_type or parsed.sport_type or planned_session.sport_type,
                discipline_variant=discipline_variant or parsed.discipline_variant or planned_session.discipline_variant,
                name=advanced.name or parsed.name or planned_session.name,
                description_text=raw_text,
                session_type=parsed.session_type or advanced.session_type or planned_session.session_type,
                session_group_id=advanced.session_group_id,
                expected_duration_min=advanced.expected_duration_min if advanced.expected_duration_min is not None else parsed.expected_duration_min,
                expected_distance_km=advanced.expected_distance_km if advanced.expected_distance_km is not None else parsed.expected_distance_km,
                expected_elevation_gain_m=advanced.expected_elevation_gain_m,
                target_type=advanced.target_type or planned_session.target_type,
                target_hr_zone=advanced.target_hr_zone or planned_session.target_hr_zone,
                target_pace_zone=advanced.target_pace_zone or planned_session.target_pace_zone,
                target_power_zone=advanced.target_power_zone or planned_session.target_power_zone,
                target_rpe_zone=advanced.target_rpe_zone or planned_session.target_rpe_zone,
                target_notes=advanced.target_notes,
                is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
            ),
        )
        replace_steps_for_session(db, updated_session, _build_builder_steps_for_updated_session(updated_session, builder_blocks_json))
        return type("QuickResult", (), {"planned_session": updated_session})

    raise ValueError("Modo de edicion no valido.")


def _build_default_steps_for_updated_session(planned_session) -> list[PlannedSessionStepCreate]:
    duration_sec = planned_session.expected_duration_min * 60 if planned_session.expected_duration_min is not None else None
    distance_m = int(round(planned_session.expected_distance_km * 1000)) if planned_session.expected_distance_km is not None else None
    if duration_sec is None and distance_m is None:
        return []
    return [
        PlannedSessionStepCreate(
            **normalize_step_target_fields(
                {
                    "planned_session_id": planned_session.id,
                    "step_order": 1,
                    "step_type": "steady",
                    "repeat_count": None,
                    "duration_sec": duration_sec,
                    "distance_m": distance_m,
                    "target_type": planned_session.target_type,
                    "target_hr_zone": planned_session.target_hr_zone,
                    "target_pace_zone": planned_session.target_pace_zone,
                    "target_power_zone": planned_session.target_power_zone,
                    "target_rpe_zone": planned_session.target_rpe_zone,
                    "target_notes": planned_session.target_notes,
                },
                planned_session.athlete,
            )
        )
    ]


def _build_parsed_steps_for_updated_session(planned_session, parsed) -> list[PlannedSessionStepCreate]:
    if parsed.steps:
        return [
            PlannedSessionStepCreate(
                planned_session_id=planned_session.id,
                step_order=step.step_order,
                step_type=step.step_type,
                repeat_count=step.repeat_count,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_notes=step.target_notes,
            )
            for step in parsed.steps
        ]
    return _build_default_steps_for_updated_session(planned_session)


def _build_builder_steps_for_updated_session(planned_session, builder_blocks_json: str | None) -> list[PlannedSessionStepCreate]:
    try:
        blocks = json.loads(builder_blocks_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("La estructura de bloques no es valida.") from exc

    steps: list[PlannedSessionStepCreate] = []
    step_order = 1
    for block in blocks:
        kind = (block.get("kind") or "").strip().lower()
        if kind == "repeat":
            repeat_count = _coerce_positive_int(block.get("repeatCount"))
            nested_steps = block.get("steps") or []
            if not repeat_count or not nested_steps:
                continue
            for index, nested in enumerate(nested_steps, start=1):
                steps.append(
                    _builder_step_create_from_payload(
                        planned_session=planned_session,
                        payload=nested,
                        step_order=step_order,
                        repeat_count=repeat_count,
                        fallback_step_type="work" if index == 1 else "recovery",
                    )
                )
                step_order += 1
        elif kind == "simple":
            steps.append(
                _builder_step_create_from_payload(
                    planned_session=planned_session,
                    payload=block,
                    step_order=step_order,
                    repeat_count=None,
                    fallback_step_type="steady",
                )
            )
            step_order += 1

    return steps or _build_default_steps_for_updated_session(planned_session)


def _builder_step_create_from_payload(*, planned_session, payload: dict, step_order: int, repeat_count: int | None, fallback_step_type: str) -> PlannedSessionStepCreate:
    value = str(payload.get("value") or "").strip()
    unit = str(payload.get("unit") or "").strip().lower()
    target_type = (payload.get("targetType") or "").strip().lower() or None
    target_zone = (payload.get("targetZone") or "").strip() or None
    custom_min = (payload.get("customMin") or "").strip() or None
    custom_max = (payload.get("customMax") or "").strip() or None
    duration_sec, distance_m = _builder_value_to_metrics(value, unit)
    step_type = (payload.get("stepType") or "").strip().lower() or fallback_step_type

    step_data: dict[str, object] = {
        "planned_session_id": planned_session.id,
        "step_order": step_order,
        "step_type": step_type,
        "repeat_count": repeat_count,
        "duration_sec": duration_sec,
        "distance_m": distance_m,
        "target_type": target_type,
        "target_hr_zone": None,
        "target_pace_zone": None,
        "target_power_zone": None,
        "target_rpe_zone": None,
        "target_hr_min": None,
        "target_hr_max": None,
        "target_power_min": None,
        "target_power_max": None,
        "target_pace_min_sec_km": None,
        "target_pace_max_sec_km": None,
    }

    if target_type == "hr":
        if target_zone == "__custom__":
            step_data["target_hr_min"] = _parse_optional_int(custom_min)
            step_data["target_hr_max"] = _parse_optional_int(custom_max)
        else:
            step_data["target_hr_zone"] = target_zone
    elif target_type == "pace":
        if target_zone == "__custom__":
            step_data["target_pace_min_sec_km"] = _parse_pace_to_seconds(custom_min)
            step_data["target_pace_max_sec_km"] = _parse_pace_to_seconds(custom_max)
        else:
            step_data["target_pace_zone"] = target_zone
    elif target_type == "power":
        if target_zone == "__custom__":
            step_data["target_power_min"] = _parse_optional_int(custom_min)
            step_data["target_power_max"] = _parse_optional_int(custom_max)
        else:
            step_data["target_power_zone"] = target_zone
    elif target_type == "rpe":
        step_data["target_rpe_zone"] = target_zone

    target_note = _builder_step_note_from_payload(payload, target_type, target_zone)
    if target_note:
        step_data["target_notes"] = target_note

    return PlannedSessionStepCreate(**normalize_step_target_fields(step_data, planned_session.athlete))


def _builder_value_to_metrics(value: str, unit: str) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    numeric_value = float(value.replace(",", "."))
    if unit == "seg":
        return int(round(numeric_value)), None
    if unit == "min":
        return int(round(numeric_value * 60)), None
    if unit == "h":
        return int(round(numeric_value * 3600)), None
    if unit == "m":
        return None, int(round(numeric_value))
    if unit == "km":
        return None, int(round(numeric_value * 1000))
    return None, None


def _builder_step_note_from_payload(payload: dict, target_type: str | None, target_zone: str | None) -> str | None:
    if target_zone and target_zone not in {"", "__custom__"}:
        return target_zone
    if target_zone == "__custom__":
        custom_min = (payload.get("customMin") or "").strip()
        custom_max = (payload.get("customMax") or "").strip()
        if target_type == "pace":
            return f"ritmo {custom_min}-{custom_max}".strip("-")
        if target_type == "hr":
            return f"FC {custom_min}-{custom_max}".strip("-")
        if target_type == "power":
            return f"potencia {custom_min}-{custom_max}".strip("-")
    return None


def _parse_pace_to_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", normalized)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    if seconds > 59:
        return None
    return minutes * 60 + seconds


def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
