from __future__ import annotations

from datetime import date
from typing import Tuple, List

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.services.session_completion_service import is_manually_completed_strength_session, has_linked_activity


def get_completed_activities_for_period(
    db: Session,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> Tuple[List[GarminActivity], List[PlannedSession]]:
    """
    Returns Garmin activities and manually completed strength sessions for the athlete
    in the inclusive date range. PlannedSession list includes strength sessions that are
    marked as manually completed or completed (but may be linked to Garmin activities).
    """
    garmin_activities = list(
        db.scalars(
            select(GarminActivity)
            .where(
                GarminActivity.athlete_id == athlete_id,
                GarminActivity.start_time.is_not(None),
            )
            .options(selectinload(GarminActivity.activity_match))
            .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
        ).all()
    )

    planned_sessions = list(
        db.scalars(
            select(PlannedSession)
            .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
            .where(
                PlannedSession.athlete_id == athlete_id,
                TrainingDay.day_date >= date_from,
                TrainingDay.day_date <= date_to,
            )
            .options(selectinload(PlannedSession.activity_match), selectinload(PlannedSession.training_day))
            .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc())
        ).all()
    )

    # Filter only strength sessions that are completed or manually completed
    strength_sessions = []
    for session in planned_sessions:
        if (str(session.sport_type or "").strip().lower() != "strength"):
            continue
        if is_manually_completed_strength_session(session) or has_linked_activity(session) or session.completed:
            strength_sessions.append(session)

    return garmin_activities, strength_sessions
