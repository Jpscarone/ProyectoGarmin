from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.activity_matching_service import (
    match_activity_to_plan,
    match_day_activities,
    match_recent_activities,
)


router = APIRouter(prefix="/match", tags=["activity_matching"])


@router.post("/activity/{activity_id}")
def match_activity(activity_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    result = match_activity_to_plan(db, activity_id)
    return RedirectResponse(
        url=f"/activities/{activity_id}?match_status={quote(result.message)}",
        status_code=303,
    )


@router.post("/day/{training_day_id}")
def match_day(training_day_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    result = match_day_activities(db, training_day_id)
    summary = f"Revisadas {result.processed}, vinculadas {result.matched}, sin vincular {result.unmatched}."
    return RedirectResponse(
        url=f"/training_days/{training_day_id}?match_status={quote(summary)}",
        status_code=303,
    )


@router.post("/recent")
def match_recent(db: Session = Depends(get_db)) -> RedirectResponse:
    result = match_recent_activities(db)
    summary = f"Revisadas {result.processed}, vinculadas {result.matched}, sin vincular {result.unmatched}."
    return RedirectResponse(
        url=f"/activities?match_status={quote(summary)}",
        status_code=303,
    )
