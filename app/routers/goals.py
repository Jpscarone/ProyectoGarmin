from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.goal import GoalCreate, GoalRead, GoalUpdate
from app.services.auth_context import require_current_user
from app.services.athlete_service import get_athletes
from app.services.goal_service import create_goal, delete_goal, get_goal, get_goals, update_goal
from app.services.user_permission_service import ROLE_ADMIN, get_permission_for_athlete, list_accessible_athletes, require_can_edit_athlete, require_can_view_athlete
from app.web.templates import build_templates


router = APIRouter(prefix="/goals", tags=["goals"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[GoalRead])
def list_goals(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    goals = get_goals(db)
    if user.role != ROLE_ADMIN:
        accessible_ids = {athlete.id for athlete in list_accessible_athletes(db, user)}
        goals = [goal for goal in goals if goal.athlete_id in accessible_ids]
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="goals/list.html",
            context={"goals": goals},
        )
    return goals


@router.get("/create", response_class=HTMLResponse)
def create_goal_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = require_current_user(request, db)
    athletes = get_athletes(db) if user.role == ROLE_ADMIN else [
        athlete
        for athlete in list_accessible_athletes(db, user)
        if (permission := get_permission_for_athlete(db, user, athlete.id)) is not None and permission.can_edit
    ]
    if not athletes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para crear objetivos.")
    return templates.TemplateResponse(
        request=request,
        name="goals/create.html",
        context={"goal": None, "athletes": athletes},
    )


@router.get("/{goal_id}", response_model=GoalRead)
def read_goal(goal_id: int, request: Request, db: Session = Depends(get_db)) -> GoalRead:
    user = require_current_user(request, db)
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    require_can_view_athlete(db, user, goal.athlete_id)
    return goal


@router.get("/{goal_id}/edit", response_class=HTMLResponse)
def edit_goal_page(goal_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = require_current_user(request, db)
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    require_can_edit_athlete(db, user, goal.athlete_id)
    athletes = get_athletes(db) if user.role == ROLE_ADMIN else [
        athlete
        for athlete in list_accessible_athletes(db, user)
        if (permission := get_permission_for_athlete(db, user, athlete.id)) is not None and permission.can_edit
    ]

    return templates.TemplateResponse(
        request=request,
        name="goals/edit.html",
        context={"goal": goal, "athletes": athletes},
    )


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal_endpoint(goal_in: GoalCreate, request: Request, db: Session = Depends(get_db)) -> GoalRead:
    user = require_current_user(request, db)
    require_can_edit_athlete(db, user, goal_in.athlete_id)
    return create_goal(db, goal_in)


@router.put("/{goal_id}", response_model=GoalRead)
def update_goal_endpoint(goal_id: int, goal_in: GoalUpdate, request: Request, db: Session = Depends(get_db)) -> GoalRead:
    user = require_current_user(request, db)
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    require_can_edit_athlete(db, user, goal.athlete_id)
    if goal_in.athlete_id is not None:
        require_can_edit_athlete(db, user, goal_in.athlete_id)
    return update_goal(db, goal, goal_in)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_goal_endpoint(goal_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    user = require_current_user(request, db)
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    require_can_edit_athlete(db, user, goal.athlete_id)
    delete_goal(db, goal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
