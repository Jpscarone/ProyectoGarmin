from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.session_group import SessionGroupCreate, SessionGroupRead, SessionGroupUpdate
from app.services.auth_context import require_current_user
from app.services.session_group_service import create_group, delete_group, get_group, update_group
from app.services.training_day_service import get_training_day
from app.services.user_permission_service import require_can_edit_athlete, require_can_view_athlete
from app.web.templates import build_templates
from app.routers._athlete_access import assert_same_athlete, get_athlete_id_from_session_group


router = APIRouter(prefix="/session_groups", tags=["session_groups"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("/create", response_class=HTMLResponse)
def create_session_group_page(
    request: Request,
    training_day_id: int = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = require_current_user(request, db)
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    require_can_edit_athlete(db, user, training_day.athlete_id)

    return templates.TemplateResponse(
        request=request,
        name="session_groups/create.html",
        context={"session_group": None, "training_day": training_day},
    )


@router.get("/{group_id}", response_model=SessionGroupRead)
def read_session_group(group_id: int, request: Request, db: Session = Depends(get_db)) -> SessionGroupRead:
    user = require_current_user(request, db)
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group not found")
    athlete_id = get_athlete_id_from_session_group(group)
    if athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group athlete not found")
    require_can_view_athlete(db, user, athlete_id)
    return group


@router.get("/{group_id}/edit", response_class=HTMLResponse)
def edit_session_group_page(group_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = require_current_user(request, db)
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group not found")
    athlete_id = get_athlete_id_from_session_group(group)
    if athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group athlete not found")
    require_can_edit_athlete(db, user, athlete_id)

    training_day = get_training_day(db, group.training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")

    return templates.TemplateResponse(
        request=request,
        name="session_groups/edit.html",
        context={"session_group": group, "training_day": training_day},
    )


@router.post("", response_model=SessionGroupRead, status_code=status.HTTP_201_CREATED)
def create_session_group_endpoint(group_in: SessionGroupCreate, request: Request, db: Session = Depends(get_db)) -> SessionGroupRead:
    user = require_current_user(request, db)
    training_day = get_training_day(db, group_in.training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    require_can_edit_athlete(db, user, training_day.athlete_id)
    try:
        return create_group(db, group_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{group_id}", response_model=SessionGroupRead)
def update_session_group_endpoint(
    group_id: int,
    group_in: SessionGroupUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> SessionGroupRead:
    user = require_current_user(request, db)
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group not found")
    current_athlete_id = get_athlete_id_from_session_group(group)
    if current_athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group athlete not found")
    require_can_edit_athlete(db, user, current_athlete_id)
    if group_in.training_day_id is not None:
        target_training_day = get_training_day(db, group_in.training_day_id)
        if target_training_day is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
        require_can_edit_athlete(db, user, target_training_day.athlete_id)
        assert_same_athlete(
            current_athlete_id,
            target_training_day.athlete_id,
            detail="No puedes mover un grupo entre atletas distintos.",
        )
    try:
        return update_group(db, group, group_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_session_group_endpoint(group_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    user = require_current_user(request, db)
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group not found")
    athlete_id = get_athlete_id_from_session_group(group)
    if athlete_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session group athlete not found")
    require_can_edit_athlete(db, user, athlete_id)
    delete_group(db, group)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
