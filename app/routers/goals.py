from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.goal import GoalCreate, GoalRead, GoalUpdate
from app.services.athlete_service import get_athletes
from app.services.goal_service import create_goal, delete_goal, get_goal, get_goals, update_goal
from app.web.templates import build_templates


router = APIRouter(prefix="/goals", tags=["goals"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[GoalRead])
def list_goals(request: Request, db: Session = Depends(get_db)):
    goals = get_goals(db)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="goals/list.html",
            context={"goals": goals},
        )
    return goals


@router.get("/create", response_class=HTMLResponse)
def create_goal_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="goals/create.html",
        context={"goal": None, "athletes": get_athletes(db)},
    )


@router.get("/{goal_id}", response_model=GoalRead)
def read_goal(goal_id: int, db: Session = Depends(get_db)) -> GoalRead:
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.get("/{goal_id}/edit", response_class=HTMLResponse)
def edit_goal_page(goal_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

    return templates.TemplateResponse(
        request=request,
        name="goals/edit.html",
        context={"goal": goal, "athletes": get_athletes(db)},
    )


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal_endpoint(goal_in: GoalCreate, db: Session = Depends(get_db)) -> GoalRead:
    return create_goal(db, goal_in)


@router.put("/{goal_id}", response_model=GoalRead)
def update_goal_endpoint(goal_id: int, goal_in: GoalUpdate, db: Session = Depends(get_db)) -> GoalRead:
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return update_goal(db, goal, goal_in)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_goal_endpoint(goal_id: int, db: Session = Depends(get_db)) -> Response:
    goal = get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    delete_goal(db, goal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
