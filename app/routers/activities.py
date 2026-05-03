from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.schemas.garmin_activity import GarminActivityDetailRead, GarminActivityRead
from app.services.activity_matching_service import run_downstream_analyses_for_match_decision
from app.services.activity_auto_sync_service import run_activity_auto_sync
from app.services.analysis_v2.session_analysis_service import ANALYSIS_VERSION
from app.services.athlete_context import get_current_athlete, get_current_training_plan
from app.config import get_settings
from app.services.garmin_activity_service import get_activities, get_activity
from app.services.session_match_service import (
    auto_match_activity,
    auto_match_unlinked_activities,
    find_candidate_sessions_for_activity,
    find_manual_sessions_for_activity,
    manual_match_activity,
    preview_activity_match,
)
from app.services.training_plan_service import get_training_plan, get_training_plans_for_athlete
from app.services.weather.weather_service import ActivityWeatherSyncError, sync_weather_for_activity
from app.web.templates import build_templates


router = APIRouter(prefix="/activities", tags=["activities"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[GarminActivityRead])
def list_activities(
    request: Request,
    athlete_id: str | None = Query(default=None),
    training_plan_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    link_filter: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    parsed_athlete_id = _parse_optional_int_query(athlete_id, "athlete_id")
    parsed_training_plan_id = _parse_optional_int_query(training_plan_id, "training_plan_id")
    current_athlete = get_current_athlete(request, db, athlete_id=parsed_athlete_id)
    if current_athlete is None and _wants_html(request):
        return RedirectResponse(url="/athletes/select", status_code=303)
    if current_athlete is not None:
        parsed_athlete_id = current_athlete.id
    auto_sync_status: dict[str, object] | None = None
    if current_athlete is not None and _wants_html(request):
        auto_sync_status = run_activity_auto_sync(
            db,
            athlete=current_athlete,
            settings=get_settings(),
        )
    selected_plan = get_training_plan(db, parsed_training_plan_id) if parsed_training_plan_id is not None else None
    if selected_plan is None and current_athlete is not None:
        selected_plan = get_current_training_plan(request, db, current_athlete, training_plan_id=parsed_training_plan_id)
        parsed_training_plan_id = selected_plan.id if selected_plan is not None else parsed_training_plan_id
    if parsed_training_plan_id is not None and selected_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")
    if selected_plan is not None and selected_plan.athlete_id != parsed_athlete_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El plan no pertenece al atleta seleccionado.")
    parsed_date_from = _parse_optional_date(date_from, "date_from") if date_from else None
    parsed_date_to = _parse_optional_date(date_to, "date_to") if date_to else None
    effective_athlete_id = parsed_athlete_id or (selected_plan.athlete_id if selected_plan else None)
    effective_date_from = parsed_date_from or (selected_plan.start_date if selected_plan else None)
    effective_date_to = parsed_date_to or (selected_plan.end_date if selected_plan else None)
    activities = get_activities(
        db,
        athlete_id=effective_athlete_id,
        date_from=effective_date_from,
        date_to=effective_date_to,
    )
    activities = _filter_activities_by_plan_link(activities, selected_plan, link_filter)
    if _wants_html(request):
        match_previews: dict[int, object] = {}
        activity_plan_context: dict[int, dict[str, object]] = {}
        has_pending_candidates = False
        for activity in activities:
            activity_plan_context[activity.id] = _build_activity_plan_context(activity, selected_plan)
            if activity.activity_match and activity.activity_match.planned_session:
                continue
            preview = preview_activity_match(db, activity.id, training_plan_id=parsed_training_plan_id)
            match_previews[activity.id] = preview
            if preview.status in {"candidate", "ambiguous"}:
                has_pending_candidates = True
        plan_options = get_training_plans_for_athlete(db, effective_athlete_id) if effective_athlete_id is not None else []
        summary = _build_activity_list_summary(activities, selected_plan)
        return templates.TemplateResponse(
            request=request,
            name="activities/list.html",
            context={
                "activities": activities,
                "plan_options": plan_options,
                "selected_plan": selected_plan,
                "selected_training_plan_id": parsed_training_plan_id,
                "selected_date_from": effective_date_from,
                "selected_date_to": effective_date_to,
                "selected_link_filter": link_filter or "",
                "activity_plan_context": activity_plan_context,
                "match_previews": match_previews,
                "has_pending_candidates": has_pending_candidates,
                "activity_summary": summary,
                "activity_auto_sync_status": auto_sync_status,
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
    current_athlete = get_current_athlete(request, db, athlete_id=activity.athlete_id)
    if current_athlete is not None and activity.athlete_id != current_athlete.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La actividad no pertenece al atleta seleccionado.")
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
    training_plan_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    current_athlete = get_current_athlete(request, db, athlete_id=activity.athlete_id, require_selected=True)
    if current_athlete is not None and activity.athlete_id != current_athlete.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La actividad no pertenece al atleta seleccionado.")
    try:
        decision = auto_match_activity(db, activity_id, training_plan_id=training_plan_id)
    except ValueError as exc:
        if _wants_html(request):
            return RedirectResponse(url=f"/activities/{activity_id}?match_status={quote(str(exc))}", status_code=303)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    weather_note = _maybe_sync_weather_after_match(db, decision)
    run_downstream_analyses_for_match_decision(db, decision)
    if _wants_html(request):
        target = (return_to or "").strip().lower()
        if target == "list":
            suffix = f"&training_plan_id={training_plan_id}" if training_plan_id is not None else ""
            redirect_url = f"/activities?match_status={quote(_activity_match_message(decision, weather_note))}{suffix}"
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
    training_plan_id: int | None = None,
    db: Session = Depends(get_db),
):
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
    selected_plan = get_training_plan(db, training_plan_id) if training_plan_id is not None else None
    parsed_date_from = _parse_optional_date(date_from, "date_from")
    parsed_date_to = _parse_optional_date(date_to, "date_to")
    if selected_plan is not None:
        athlete_id = athlete_id or selected_plan.athlete_id
        parsed_date_from = parsed_date_from or selected_plan.start_date
        parsed_date_to = parsed_date_to or selected_plan.end_date
    batch = auto_match_unlinked_activities(
        db,
        athlete_id=athlete_id,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        only_unmatched=only_unmatched,
        training_plan_id=training_plan_id,
    )
    for decision in batch.decisions:
        run_downstream_analyses_for_match_decision(db, decision)

    if _wants_html(request):
        message = (
            f"Revisadas {batch.processed}. "
            f"Vinculadas {batch.matched}, candidatas {batch.candidate}, ambiguas {batch.ambiguous}, sin match {batch.unmatched}."
        )
        suffix = f"&training_plan_id={training_plan_id}" if training_plan_id is not None else ""
        return RedirectResponse(url=f"/activities?match_status={quote(message)}{suffix}", status_code=303)
    return batch.to_dict()


@router.post("/{activity_id}/manual-match")
def manual_match_activity_endpoint(
    activity_id: int,
    request: Request,
    planned_session_id: int = Form(...),
    db: Session = Depends(get_db),
):
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    current_athlete = get_current_athlete(request, db, athlete_id=activity.athlete_id, require_selected=True)
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


@router.get("/{activity_id}/match-candidates")
def activity_match_candidates_endpoint(
    activity_id: int,
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    sport_type: str | None = None,
    only_unmatched: bool = False,
    training_plan_id: int | None = None,
    db: Session = Depends(get_db),
):
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    current_athlete = get_current_athlete(request, db, athlete_id=activity.athlete_id, require_selected=True)
    if current_athlete is not None and activity.athlete_id != current_athlete.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La actividad no pertenece al atleta seleccionado.")
    parsed_date_from = _parse_optional_date(date_from, "date_from") if date_from else None
    parsed_date_to = _parse_optional_date(date_to, "date_to") if date_to else None
    try:
        candidates = find_manual_sessions_for_activity(
            db,
            activity_id,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
            sport_type=sport_type,
            only_unmatched=only_unmatched,
            training_plan_id=training_plan_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session_ids = [item.planned_session_id for item in candidates]
    sessions = {}
    if session_ids:
        statement = select(PlannedSession).where(PlannedSession.id.in_(session_ids))
        sessions = {item.id: item for item in db.scalars(statement).all()}

    candidate_payload = []
    for item in candidates[:5]:
        session = sessions.get(item.planned_session_id)
        payload = item.to_dict()
        payload["expected_duration_min"] = session.expected_duration_min if session else None
        payload["expected_distance_km"] = session.expected_distance_km if session else None
        payload["session_url"] = f"/planned_sessions/{item.planned_session_id}"
        payload["training_plan_id"] = item.training_plan_id
        payload["training_plan_name"] = item.training_plan_name
        payload["is_current_plan"] = training_plan_id is not None and item.training_plan_id == training_plan_id
        candidate_payload.append(payload)

    return {
        "activity": {
            "id": activity.id,
            "start_time": activity.start_time.isoformat() if activity.start_time else None,
            "sport_type": activity.sport_type,
            "activity_name": activity.activity_name,
            "duration_sec": activity.duration_sec,
            "distance_m": activity.distance_m,
        },
        "candidates": candidate_payload,
    }


@router.post("/{activity_id}/link-session")
async def link_activity_to_session_endpoint(
    activity_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    current_athlete = get_current_athlete(request, db, athlete_id=activity.athlete_id, require_selected=True)
    if current_athlete is not None and activity.athlete_id != current_athlete.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La actividad no pertenece al atleta seleccionado.")
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta planned_session_id")
    planned_session_id = payload.get("planned_session_id")
    if not planned_session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta planned_session_id")

    try:
        decision = manual_match_activity(db, activity_id, int(planned_session_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    run_downstream_analyses_for_match_decision(db, decision)
    if _wants_html(request):
        return RedirectResponse(
            url=f"/activities?match_status={quote(f'Actividad vinculada manualmente con la sesion #{planned_session_id}.')}",
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


def _parse_optional_int_query(raw_value: str | None, field_name: str) -> int | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} invalido") from exc


def _parse_optional_date(raw_value: str | None, field_name: str):
    if not raw_value:
        return None
    try:
        from datetime import date

        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} invalida") from exc


def _build_activity_list_summary(activities, selected_plan: TrainingPlan | None) -> dict[str, object]:
    linked_count = 0
    unlinked_count = 0
    weather_count = 0
    for activity in activities:
        if activity.activity_match and activity.activity_match.planned_session:
            linked_count += 1
        else:
            unlinked_count += 1
        if activity.weather is not None:
            weather_count += 1

    return {
        "count": len(activities),
        "linked_count": linked_count,
        "unlinked_count": unlinked_count,
        "weather_count": weather_count,
        "plan_name": selected_plan.name if selected_plan is not None else None,
        "plan_date_range": (
            f"{selected_plan.start_date.isoformat()} - {selected_plan.end_date.isoformat()}"
            if selected_plan is not None and selected_plan.start_date is not None and selected_plan.end_date is not None
            else None
        ),
    }


def _filter_activities_by_plan_link(activities, selected_plan: TrainingPlan | None, link_filter: str | None):
    if not link_filter:
        return activities
    filtered = []
    for activity in activities:
        context = _build_activity_plan_context(activity, selected_plan)
        if link_filter == "unlinked" and context["state"] == "unlinked":
            filtered.append(activity)
        elif link_filter == "linked_this_plan" and context["state"] == "linked_this_plan":
            filtered.append(activity)
        elif link_filter == "linked_other_plan" and context["state"] == "linked_other_plan":
            filtered.append(activity)
    return filtered


def _build_activity_plan_context(activity, selected_plan: TrainingPlan | None) -> dict[str, object]:
    match = activity.activity_match
    if match is None or match.planned_session is None:
        return {"state": "unlinked", "label": "Sin vincular", "plan_name": None}
    session_plan = match.planned_session.training_day.training_plan if match.planned_session.training_day else None
    if selected_plan is not None and session_plan is not None and session_plan.id == selected_plan.id:
        return {"state": "linked_this_plan", "label": "Vinculada a este plan", "plan_name": session_plan.name}
    if selected_plan is not None and session_plan is not None:
        return {"state": "linked_other_plan", "label": "Vinculada a otro plan", "plan_name": session_plan.name}
    return {"state": "linked", "label": "Vinculada", "plan_name": session_plan.name if session_plan else None}


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
