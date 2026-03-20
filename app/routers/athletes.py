from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.athlete import AthleteCreate, AthleteRead, AthleteUpdate
from app.services.athlete_service import (
    create_athlete,
    delete_athlete,
    get_athlete,
    get_athletes,
    update_athlete,
)
from app.web.templates import build_templates


router = APIRouter(prefix="/athletes", tags=["athletes"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[AthleteRead])
def list_athletes(request: Request, db: Session = Depends(get_db)):
    athletes = get_athletes(db)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="athletes/list.html",
            context={"athletes": athletes},
        )
    return athletes


@router.get("/create", response_class=HTMLResponse)
def create_athlete_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="athletes/create.html",
        context={"athlete": None},
    )


@router.get("/{athlete_id}", response_model=AthleteRead)
def read_athlete(athlete_id: int, db: Session = Depends(get_db)) -> AthleteRead:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    return athlete


@router.get("/{athlete_id}/edit", response_class=HTMLResponse)
def edit_athlete_page(athlete_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    return templates.TemplateResponse(
        request=request,
        name="athletes/edit.html",
        context={"athlete": athlete},
    )


@router.post("", response_model=AthleteRead, status_code=status.HTTP_201_CREATED)
def create_athlete_endpoint(athlete_in: AthleteCreate, db: Session = Depends(get_db)) -> AthleteRead:
    return create_athlete(db, athlete_in)


@router.put("/{athlete_id}", response_model=AthleteRead)
def update_athlete_endpoint(
    athlete_id: int,
    athlete_in: AthleteUpdate,
    db: Session = Depends(get_db),
) -> AthleteRead:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    return update_athlete(db, athlete, athlete_in)


@router.delete("/{athlete_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_athlete_endpoint(athlete_id: int, db: Session = Depends(get_db)) -> Response:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    delete_athlete(db, athlete)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
