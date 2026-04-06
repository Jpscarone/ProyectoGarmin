from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.garmin_activity import GarminActivityDetailRead, GarminActivityRead
from app.services.analysis.report_service import get_latest_activity_report
from app.services.activity_matching_service import run_downstream_analyses_for_match_decision
from app.services.garmin_activity_service import get_activities, get_activity
from app.services.session_match_service import (
    auto_match_activity,
    auto_match_unlinked_activities,
    manual_match_activity,
    preview_activity_match,
)
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
                "latest_report": get_latest_activity_report(db, activity.id),
                "weather_status": request.query_params.get("weather_status"),
                "match_status": request.query_params.get("match_status"),
                "analysis_status": request.query_params.get("analysis_status"),
            },
        )
    return activity


@router.post("/{activity_id}/auto-match")
def auto_match_activity_endpoint(activity_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        decision = auto_match_activity(db, activity_id)
    except ValueError as exc:
        if _wants_html(request):
            return RedirectResponse(url=f"/activities/{activity_id}?match_status={quote(str(exc))}", status_code=303)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    run_downstream_analyses_for_match_decision(db, decision)
    if _wants_html(request):
        return RedirectResponse(
            url=f"/activities/{activity_id}?match_status={quote(_activity_match_message(decision))}",
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


def _activity_match_message(decision) -> str:
    if decision.status == "matched":
        return (
            f"Actividad vinculada con la sesion #{decision.matched_session_id}. "
            f"Score {decision.score:.1f}."
        )
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
