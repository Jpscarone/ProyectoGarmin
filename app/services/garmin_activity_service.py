from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity


def get_activities(db: Session) -> list[GarminActivity]:
    statement = (
        select(GarminActivity)
        .options(
            selectinload(GarminActivity.weather),
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )
    return list(db.scalars(statement).all())


def get_activity(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.laps),
            selectinload(GarminActivity.athlete),
            selectinload(GarminActivity.weather),
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.training_day),
        )
    )
    return db.scalar(statement)
