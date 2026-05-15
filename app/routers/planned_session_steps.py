from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.planned_session_step import PlannedSessionStepCreate, PlannedSessionStepRead, PlannedSessionStepUpdate
from app.services.auth_context import require_current_user
from app.services.planned_session_service import get_planned_session
from app.services.planned_session_step_service import create_step, delete_step, get_step, update_step
from app.services.user_permission_service import require_can_edit_athlete, require_can_view_athlete
from app.routers._athlete_access import assert_same_athlete, get_athlete_id_from_step


router = APIRouter(prefix="/planned_session_steps", tags=["planned_session_steps"])


@router.get("/{step_id}", response_model=PlannedSessionStepRead)
def read_planned_session_step(step_id: int, request: Request, db: Session = Depends(get_db)) -> PlannedSessionStepRead:
    user = require_current_user(request, db)
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")
    athlete_id = get_athlete_id_from_step(step)
    if athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step athlete not found")
    require_can_view_athlete(db, user, athlete_id)
    return step


@router.post("", response_model=PlannedSessionStepRead, status_code=status.HTTP_201_CREATED)
def create_planned_session_step_endpoint(
    step_in: PlannedSessionStepCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> PlannedSessionStepRead:
    user = require_current_user(request, db)
    planned_session = get_planned_session(db, step_in.planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    require_can_edit_athlete(db, user, planned_session.athlete_id)
    try:
        return create_step(db, step_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{step_id}", response_model=PlannedSessionStepRead)
def update_planned_session_step_endpoint(
    step_id: int,
    step_in: PlannedSessionStepUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> PlannedSessionStepRead:
    user = require_current_user(request, db)
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")
    current_athlete_id = get_athlete_id_from_step(step)
    if current_athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step athlete not found")
    require_can_edit_athlete(db, user, current_athlete_id)
    if step_in.planned_session_id is not None:
        target_session = get_planned_session(db, step_in.planned_session_id)
        if target_session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
        require_can_edit_athlete(db, user, target_session.athlete_id)
        assert_same_athlete(
            current_athlete_id,
            target_session.athlete_id,
            detail="No puedes mover un paso entre atletas distintos.",
        )
    try:
        return update_step(db, step, step_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{step_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_planned_session_step_endpoint(step_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    user = require_current_user(request, db)
    step = get_step(db, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step not found")
    athlete_id = get_athlete_id_from_step(step)
    if athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session step athlete not found")
    require_can_edit_athlete(db, user, athlete_id)
    delete_step(db, step)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
