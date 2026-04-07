from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.session_analysis import SessionAnalysis
from app.db.session import get_db
from app.schemas.training_day import TrainingDayCreate, TrainingDayRead, TrainingDayUpdate
from app.services.analysis_v2.session_analysis_service import ANALYSIS_VERSION
from app.services.training_day_service import (
    create_training_day,
    delete_training_day,
    get_training_day,
    get_training_days,
    update_training_day,
)
from app.services.training_plan_service import get_training_plan, get_training_plans
from app.web.templates import build_templates


router = APIRouter(prefix="/training_days", tags=["training_days"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[TrainingDayRead])
def list_training_days(db: Session = Depends(get_db)) -> list[TrainingDayRead]:
    return get_training_days(db)


@router.get("/create", response_class=HTMLResponse)
def create_training_day_page(
    request: Request,
    training_plan_id: int = Query(...),
    day_date: str | None = Query(default=None),
    return_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    training_plan = get_training_plan(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")

    prefilled_training_day = None
    if day_date:
        try:
            parsed_day_date = date.fromisoformat(day_date)
            prefilled_training_day = TrainingDayCreate(
                training_plan_id=training_plan.id,
                athlete_id=training_plan.athlete_id,
                day_date=parsed_day_date,
                day_notes=None,
                day_type=None,
            )
        except ValueError:
            prefilled_training_day = None

    return templates.TemplateResponse(
        request=request,
        name="training_days/create.html",
        context={
            "training_day": prefilled_training_day,
            "training_plan": training_plan,
            "training_plans": get_training_plans(db),
            "return_to": return_to,
        },
    )


@router.get("/{training_day_id}", response_model=TrainingDayRead)
def read_training_day(training_day_id: int, request: Request, db: Session = Depends(get_db)):
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    if _wants_html(request):
        return_to = (request.query_params.get("return_to") or "").strip().lower()
        if return_to == "plan":
            back_label = "Volver a dias del plan"
            back_href = f"/training_plans/{training_day.training_plan.id}#training-day-{training_day.id}"
        else:
            back_label = "Volver al calendario"
            back_href = (
                f"/training_plans/{training_day.training_plan.id}/calendar"
                f"?month={training_day.day_date.strftime('%Y-%m')}&selected_date={training_day.day_date.isoformat()}"
            )
        latest_analysis_by_session = _get_latest_session_analyses_map(db, training_day)
        return templates.TemplateResponse(
            request=request,
            name="training_days/detail.html",
            context={
                "training_day": training_day,
                "back_label": back_label,
                "back_href": back_href,
                "ui_status": request.query_params.get("ui_status"),
                "match_status": request.query_params.get("match_status"),
                "analysis_status": request.query_params.get("analysis_status"),
                "day_analysis_view": _build_training_day_analysis_view(training_day, latest_analysis_by_session),
                "latest_analysis_by_session": latest_analysis_by_session,
            },
        )
    return training_day


@router.get("/{training_day_id}/edit", response_class=HTMLResponse)
def edit_training_day_page(
    training_day_id: int,
    request: Request,
    return_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")

    normalized_return_to = (return_to or "").strip().lower()
    if normalized_return_to == "calendar":
        back_label = "Volver al calendario"
        back_href = (
            f"/training_plans/{training_day.training_plan.id}/calendar"
            f"?month={training_day.day_date.strftime('%Y-%m')}&selected_date={training_day.day_date.isoformat()}"
        )
    else:
        back_label = "Volver a dias del plan"
        back_href = f"/training_plans/{training_day.training_plan.id}#training-day-{training_day.id}"

    return templates.TemplateResponse(
        request=request,
        name="training_days/edit.html",
        context={
            "training_day": training_day,
            "training_plan": training_day.training_plan,
            "training_plans": get_training_plans(db),
            "back_label": back_label,
            "back_href": back_href,
            "return_to": normalized_return_to or "plan",
        },
    )


@router.post("", response_model=TrainingDayRead, status_code=status.HTTP_201_CREATED)
def create_training_day_endpoint(training_day_in: TrainingDayCreate, db: Session = Depends(get_db)) -> TrainingDayRead:
    try:
        return create_training_day(db, training_day_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A day already exists for this date in the selected plan") from exc


@router.put("/{training_day_id}", response_model=TrainingDayRead)
def update_training_day_endpoint(
    training_day_id: int,
    training_day_in: TrainingDayUpdate,
    db: Session = Depends(get_db),
) -> TrainingDayRead:
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    try:
        return update_training_day(db, training_day, training_day_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A day already exists for this date in the selected plan") from exc


@router.delete("/{training_day_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_training_day_endpoint(training_day_id: int, db: Session = Depends(get_db)) -> Response:
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    delete_training_day(db, training_day)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_latest_session_analyses_map(db: Session, training_day) -> dict[int, SessionAnalysis]:
    session_ids = [session.id for session in training_day.planned_sessions]
    if not session_ids:
        return {}

    analyses = list(
        db.scalars(
            select(SessionAnalysis)
            .where(
                SessionAnalysis.planned_session_id.in_(session_ids),
                SessionAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .order_by(SessionAnalysis.analyzed_at.desc(), SessionAnalysis.id.desc())
        ).all()
    )
    latest_by_session: dict[int, SessionAnalysis] = {}
    for analysis in analyses:
        latest_by_session.setdefault(analysis.planned_session_id, analysis)
    return latest_by_session


def _build_training_day_analysis_view(training_day, latest_by_session: dict[int, SessionAnalysis]) -> dict[str, object]:
    if not training_day.planned_sessions:
        return {
            "has_items": False,
            "title": "Analisis de sesiones del dia",
            "empty_message": "Todavia no hay sesiones cargadas para este dia.",
        }

    items = []
    for planned_session in training_day.planned_sessions:
        analysis = latest_by_session.get(planned_session.id)
        if analysis is None:
            items.append(
                {
                    "session_name": planned_session.name,
                    "session_url": f"/planned_sessions/{planned_session.id}",
                    "status_label": "Pendiente",
                    "status_class": "analysis-status-neutral",
                    "score_label": "-",
                    "summary": "Todavia no hay un analisis V2 listo para esta sesion.",
                    "analysis_url": None,
                }
            )
            continue

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
        items.append(
            {
                "session_name": planned_session.name,
                "session_url": f"/planned_sessions/{planned_session.id}",
                "status_label": _analysis_v2_status_label(analysis.status),
                "status_class": _analysis_v2_status_class(analysis.status),
                "score_label": overall_score if overall_score is not None else "-",
                "summary": analysis.summary_short or analysis.coach_conclusion or "Analisis disponible.",
                "analysis_url": f"/planned_sessions/{planned_session.id}/analysis",
            }
        )

    has_ready_items = any(item["analysis_url"] for item in items)
    return {
        "has_items": True,
        "title": "Analisis de sesiones del dia",
        "items": items,
        "has_ready_items": has_ready_items,
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
