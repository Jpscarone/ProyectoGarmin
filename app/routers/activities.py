from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.session_analysis import SessionAnalysis
from app.db.session import get_db
from app.schemas.garmin_activity import GarminActivityDetailRead, GarminActivityRead
from app.services.activity_matching_service import run_downstream_analyses_for_match_decision
from app.services.analysis_v2.session_analysis_service import ANALYSIS_VERSION
from app.services.garmin_activity_service import get_activities, get_activity
from app.services.session_match_service import (
    auto_match_activity,
    auto_match_unlinked_activities,
    manual_match_activity,
    preview_activity_match,
)
from app.services.weather.weather_service import ActivityWeatherSyncError, sync_weather_for_activity
from app.web.templates import build_templates


router = APIRouter(prefix="/activities", tags=["activities"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[GarminActivityRead])
def list_activities(request: Request, db: Session = Depends(get_db)):
    activities = get_activities(db)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="activities/list.html",
            context={
                "activities": activities,
                "ui_status": request.query_params.get("ui_status"),
                "weather_status": request.query_params.get("weather_status"),
                "match_status": request.query_params.get("match_status"),
            },
        )
    return activities


@router.get("/{activity_id}", response_model=GarminActivityDetailRead)
def read_activity(activity_id: int, request: Request, db: Session = Depends(get_db)):
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    if _wants_html(request):
        match_preview = preview_activity_match(db, activity.id)
        return templates.TemplateResponse(
            request=request,
            name="activities/detail.html",
            context={
                "activity": activity,
                "match_preview": match_preview,
                "match_preview_status_label": _match_status_label(match_preview.status),
                "analysis_v2_summary": _build_activity_analysis_v2_summary(db, activity),
                "weather_status": request.query_params.get("weather_status"),
                "match_status": request.query_params.get("match_status"),
                "analysis_status": request.query_params.get("analysis_status"),
            },
        )
    return activity


@router.post("/{activity_id}/auto-match")
def auto_match_activity_endpoint(
    activity_id: int,
    request: Request,
    return_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        decision = auto_match_activity(db, activity_id)
    except ValueError as exc:
        if _wants_html(request):
            return RedirectResponse(url=f"/activities/{activity_id}?match_status={quote(str(exc))}", status_code=303)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    weather_note = _maybe_sync_weather_after_match(db, decision)
    run_downstream_analyses_for_match_decision(db, decision)
    if _wants_html(request):
        target = (return_to or "").strip().lower()
        if target == "list":
            redirect_url = f"/activities?match_status={quote(_activity_match_message(decision, weather_note))}"
        else:
            redirect_url = f"/activities/{activity_id}?match_status={quote(_activity_match_message(decision, weather_note))}"
        return RedirectResponse(
            url=redirect_url,
            status_code=303,
        )
    return decision.to_dict()


@router.post("/auto-match-pending")
def auto_match_pending_endpoint(
    request: Request,
    athlete_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    only_unmatched: bool = True,
    db: Session = Depends(get_db),
):
    parsed_date_from = _parse_optional_date(date_from, "date_from")
    parsed_date_to = _parse_optional_date(date_to, "date_to")
    batch = auto_match_unlinked_activities(
        db,
        athlete_id=athlete_id,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        only_unmatched=only_unmatched,
    )
    for decision in batch.decisions:
        run_downstream_analyses_for_match_decision(db, decision)

    if _wants_html(request):
        message = (
            f"Revisadas {batch.processed}. "
            f"Vinculadas {batch.matched}, candidatas {batch.candidate}, ambiguas {batch.ambiguous}, sin match {batch.unmatched}."
        )
        return RedirectResponse(url=f"/activities?match_status={quote(message)}", status_code=303)
    return batch.to_dict()


@router.post("/{activity_id}/manual-match")
def manual_match_activity_endpoint(
    activity_id: int,
    request: Request,
    planned_session_id: int = Form(...),
    db: Session = Depends(get_db),
):
    try:
        decision = manual_match_activity(db, activity_id, planned_session_id)
    except ValueError as exc:
        if _wants_html(request):
            return RedirectResponse(url=f"/activities/{activity_id}?match_status={quote(str(exc))}", status_code=303)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    run_downstream_analyses_for_match_decision(db, decision)
    if _wants_html(request):
        return RedirectResponse(
            url=f"/activities/{activity_id}?match_status={quote(f'Actividad vinculada manualmente con la sesion #{planned_session_id}.')}",
            status_code=303,
        )
    return decision.to_dict()


def _activity_match_message(decision, weather_note: str | None = None) -> str:
    if decision.status == "matched":
        message = (
            f"Actividad vinculada con la sesion #{decision.matched_session_id}. "
            f"Score {decision.score:.1f}."
        )
        if weather_note:
            message = f"{message} {weather_note}"
        return message
    if decision.status == "ambiguous":
        return (
            f"Matching ambiguo. Mejor score {decision.score:.1f}. "
            "Revisar candidatas sugeridas antes de vincular."
        )
    if decision.status == "candidate":
        return (
            f"Hay una sesion candidata, pero no se vinculo automaticamente. "
            f"Score {decision.score:.1f}."
        )
    return "No se encontro una sesion confiable para vincular automaticamente."


def _parse_optional_date(raw_value: str | None, field_name: str):
    if not raw_value:
        return None
    try:
        from datetime import date

        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} invalida") from exc


def _match_status_label(value: str) -> str:
    return {
        "matched": "Vinculada",
        "candidate": "Candidata",
        "ambiguous": "Ambigua",
        "unmatched": "Sin match",
    }.get(value, value)


def _maybe_sync_weather_after_match(db: Session, decision) -> str | None:
    if decision.status != "matched":
        return None

    activity = get_activity(db, decision.activity_id)
    if activity is None or activity.weather is not None:
        return None

    try:
        result = sync_weather_for_activity(db, activity)
        return result.message
    except ActivityWeatherSyncError:
        return None
    except Exception:
        return None


def _build_activity_analysis_v2_summary(db: Session, activity) -> dict[str, object]:
    planned_session = activity.activity_match.planned_session if activity.activity_match and activity.activity_match.planned_session else None
    if planned_session is None:
        return {
            "exists": False,
            "title": "Analisis de la sesion vinculada",
            "empty_message": "Primero hace falta vincular esta actividad con una sesion planificada para poder leer su analisis V2.",
        }

    analysis = db.scalar(
        select(SessionAnalysis)
        .where(
            SessionAnalysis.activity_id == activity.id,
            SessionAnalysis.planned_session_id == planned_session.id,
            SessionAnalysis.analysis_version == ANALYSIS_VERSION,
        )
        .order_by(SessionAnalysis.analyzed_at.desc(), SessionAnalysis.id.desc())
    )
    if analysis is None:
        return {
            "exists": False,
            "title": "Analisis de la sesion vinculada",
            "empty_message": "La actividad ya esta vinculada, pero todavia no hay un analisis V2 disponible para esa sesion.",
            "session_url": f"/planned_sessions/{planned_session.id}",
        }

    score_values = [
        value
        for value in (
            analysis.compliance_score,
            analysis.execution_score,
            analysis.control_score,
            analysis.fatigue_score,
        )
        if value is not None
    ]
    overall_score = round(sum(float(value) for value in score_values) / len(score_values), 1) if score_values else None
    return {
        "exists": True,
        "title": "Analisis de la sesion vinculada",
        "session_name": planned_session.name,
        "session_url": f"/planned_sessions/{planned_session.id}",
        "analysis_url": f"/planned_sessions/{planned_session.id}/analysis",
        "status_label": _analysis_v2_status_label(analysis.status),
        "status_class": _analysis_v2_status_class(analysis.status),
        "score_label": overall_score if overall_score is not None else "-",
        "summary": analysis.summary_short or "-",
        "conclusion": analysis.coach_conclusion or "-",
        "recommendation": analysis.next_recommendation or None,
    }


def _analysis_v2_status_label(status_value: str | None) -> str:
    return {
        "completed": "Completo",
        "completed_with_warnings": "Completo con advertencias",
        "error": "Error",
        "pending": "Pendiente",
    }.get(status_value or "", "Sin analisis")


def _analysis_v2_status_class(status_value: str | None) -> str:
    return {
        "completed": "analysis-status-good",
        "completed_with_warnings": "analysis-status-warn",
        "error": "analysis-status-bad",
        "pending": "analysis-status-neutral",
    }.get(status_value or "", "analysis-status-neutral")
