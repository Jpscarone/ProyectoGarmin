from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay


def get_activities(
    db: Session,
    *,
    athlete_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    training_plan_id: int | None = None,
    link_filter: str | None = None,
) -> list[GarminActivity]:
    statement = (
        select(GarminActivity)
        .options(
            selectinload(GarminActivity.weather),
            selectinload(GarminActivity.activity_match)
            .selectinload(ActivitySessionMatch.planned_session)
            .selectinload(PlannedSession.training_day)
            .selectinload(TrainingDay.training_plan),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )
    if athlete_id is not None:
        statement = statement.where(GarminActivity.athlete_id == athlete_id)
    if date_from is not None:
        statement = statement.where(GarminActivity.start_time >= datetime.combine(date_from, time.min))
    if date_to is not None:
        statement = statement.where(GarminActivity.start_time < datetime.combine(date_to + timedelta(days=1), time.min))
    return list(db.scalars(statement).all())


def get_activity(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.laps),
            selectinload(GarminActivity.athlete),
            selectinload(GarminActivity.weather),
            selectinload(GarminActivity.activity_match)
            .selectinload(ActivitySessionMatch.planned_session)
            .selectinload(PlannedSession.training_day)
            .selectinload(TrainingDay.training_plan),
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.training_day).selectinload(TrainingDay.training_plan),
        )
    )
    return db.scalar(statement)
