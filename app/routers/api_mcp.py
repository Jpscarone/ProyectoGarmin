from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.athlete_context import get_current_athlete, get_current_training_plan
from app.services.mcp_context_service import (
    build_last_activity_feedback_payload,
    build_next_session_context_payload,
    build_session_feedback_payload,
    build_week_context_payload,
)
from app.services.mcp_security import verify_mcp_bearer_token


router = APIRouter(
    prefix="/api/mcp",
    tags=["api_mcp"],
    dependencies=[Depends(verify_mcp_bearer_token)],
)


@router.get("/session-feedback")
def read_session_feedback(
    request: Request,
    date_value: str = Query(alias="date"),
    db: Session = Depends(get_db),
):
    target_date = _parse_iso_date(date_value, "date")
    athlete = get_current_athlete(request, db)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_session_feedback_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
        target_date=target_date,
    )


@router.get("/week-context")
def read_week_context(
    request: Request,
    db: Session = Depends(get_db),
):
    athlete = get_current_athlete(request, db)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_week_context_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
    )


@router.get("/last-activity-feedback")
def read_last_activity_feedback(
    request: Request,
    db: Session = Depends(get_db),
):
    athlete = get_current_athlete(request, db)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_last_activity_feedback_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
    )


@router.get("/next-session-context")
def read_next_session_context(
    request: Request,
    db: Session = Depends(get_db),
):
    athlete = get_current_athlete(request, db)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay atleta activo disponible.")
    training_plan = get_current_training_plan(request, db, athlete)
    return build_next_session_context_payload(
        db,
        athlete=athlete,
        training_plan=training_plan,
    )


def _parse_iso_date(raw_value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} debe tener formato YYYY-MM-DD.",
        ) from exc
