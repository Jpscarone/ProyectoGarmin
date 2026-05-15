from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.auth_context import require_current_user
from app.services.athlete_context import get_current_athlete
from app.services.activity_matching_service import (
    match_activity_to_plan,
    match_day_activities,
    match_recent_activities,
    run_downstream_analyses_for_match_decision,
)
from app.services.garmin_activity_service import get_activity
from app.services.session_match_service import auto_match_unlinked_activities
from app.services.training_day_service import get_training_day
from app.services.user_permission_service import ROLE_ADMIN, require_can_edit_athlete


router = APIRouter(prefix="/match", tags=["activity_matching"])


@router.post("/activity/{activity_id}")
def match_activity(activity_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    user = require_current_user(request, db)
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    require_can_edit_athlete(db, user, activity.athlete_id)
    result = match_activity_to_plan(db, activity_id)
    return RedirectResponse(
        url=f"/activities/{activity_id}?match_status={quote(result.message)}",
        status_code=303,
    )


@router.post("/day/{training_day_id}")
def match_day(training_day_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    user = require_current_user(request, db)
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    require_can_edit_athlete(db, user, training_day.athlete_id)
    result = match_day_activities(db, training_day_id)
    summary = f"Revisadas {result.processed}, vinculadas {result.matched}, sin vincular {result.unmatched}."
    return RedirectResponse(
        url=f"/training_days/{training_day_id}?match_status={quote(summary)}",
        status_code=303,
    )


@router.post("/recent")
def match_recent(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    user = require_current_user(request, db)
    current_athlete = get_current_athlete(request, db)
    if current_athlete is None:
        if user.role != ROLE_ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Selecciona un atleta antes de ejecutar el matching reciente.")
        result = match_recent_activities(db)
    else:
        require_can_edit_athlete(db, user, current_athlete.id)
        batch = auto_match_unlinked_activities(
            db,
            athlete_id=current_athlete.id,
            only_unmatched=False,
        )
        for decision in batch.decisions:
            run_downstream_analyses_for_match_decision(db, decision)
        unmatched = batch.unmatched + batch.candidate + batch.ambiguous
        result = type("RecentMatchResult", (), {"processed": batch.processed, "matched": batch.matched, "unmatched": unmatched})()
    summary = f"Revisadas {result.processed}, vinculadas {result.matched}, sin vincular {result.unmatched}."
    return RedirectResponse(
        url=f"/activities?match_status={quote(summary)}",
        status_code=303,
    )
