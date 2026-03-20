from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.planned_session_step import PlannedSessionStepCreate, PlannedSessionStepRead, PlannedSessionStepUpdate
from app.services.planned_session_service import get_planned_session
from app.services.planned_session_step_service import create_step, delete_step, get_step, update_step
from app.web.templates import build_templates


router = APIRouter(prefix="/planned_session_steps", tags=["planned_session_steps"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("/create", response_class=HTMLResponse)
def create_planned_session_step_page(
    request: Request,
    planned_session_id: int = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")

    return templates.TemplateResponse(
        request=request,
        name="planned_session_steps/create.html",
        context={"step": None, "planned_session": planned_session},
    )


@router.get("/{step_id}", response_model=PlannedSessionStepRead)
def read_planned_session_step(step_id: int, db: Session = Depends(get_db)) -> PlannedSessionStepRead:
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")
    return step


@router.get("/{step_id}/edit", response_class=HTMLResponse)
def edit_planned_session_step_page(step_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")

    planned_session = get_planned_session(db, step.planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")

    return templates.TemplateResponse(
        request=request,
        name="planned_session_steps/edit.html",
        context={"step": step, "planned_session": planned_session},
    )


@router.post("", response_model=PlannedSessionStepRead, status_code=status.HTTP_201_CREATED)
def create_planned_session_step_endpoint(
    step_in: PlannedSessionStepCreate,
    db: Session = Depends(get_db),
) -> PlannedSessionStepRead:
    try:
        return create_step(db, step_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{step_id}", response_model=PlannedSessionStepRead)
def update_planned_session_step_endpoint(
    step_id: int,
    step_in: PlannedSessionStepUpdate,
    db: Session = Depends(get_db),
) -> PlannedSessionStepRead:
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")
    try:
        return update_step(db, step, step_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{step_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_planned_session_step_endpoint(step_id: int, db: Session = Depends(get_db)) -> Response:
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")
    delete_step(db, step)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
