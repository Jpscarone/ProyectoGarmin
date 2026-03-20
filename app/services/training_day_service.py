from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.session_group import SessionGroup
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.schemas.training_day import TrainingDayCreate, TrainingDayUpdate


def get_training_days(db: Session) -> list[TrainingDay]:
    statement = (
        select(TrainingDay)
        .options(selectinload(TrainingDay.training_plan))
        .order_by(TrainingDay.day_date.desc(), TrainingDay.id.desc())
    )
    return list(db.scalars(statement).all())


def get_training_day(db: Session, training_day_id: int) -> TrainingDay | None:
    statement = (
        select(TrainingDay)
        .where(TrainingDay.id == training_day_id)
        .options(
            selectinload(TrainingDay.training_plan),
            selectinload(TrainingDay.session_groups).selectinload(SessionGroup.planned_sessions),
            selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.planned_session_steps),
            selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.activity_match)
            .selectinload(ActivitySessionMatch.garmin_activity),
            selectinload(TrainingDay.activity_matches).selectinload(ActivitySessionMatch.garmin_activity),
        )
    )
    return db.scalar(statement)


def get_training_day_by_plan_and_date(db: Session, training_plan_id: int, day_date) -> TrainingDay | None:
    statement = (
        select(TrainingDay)
        .where(TrainingDay.training_plan_id == training_plan_id, TrainingDay.day_date == day_date)
        .options(
            selectinload(TrainingDay.training_plan),
            selectinload(TrainingDay.session_groups).selectinload(SessionGroup.planned_sessions),
            selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.planned_session_steps),
            selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.activity_match)
            .selectinload(ActivitySessionMatch.garmin_activity),
            selectinload(TrainingDay.activity_matches).selectinload(ActivitySessionMatch.garmin_activity),
        )
    )
    return db.scalar(statement)


def create_training_day(db: Session, training_day_in: TrainingDayCreate) -> TrainingDay:
    training_plan = db.get(TrainingPlan, training_day_in.training_plan_id)
    if training_plan is None:
        raise ValueError("Training plan not found")

    data = training_day_in.model_dump()
    data["athlete_id"] = training_plan.athlete_id

    training_day = TrainingDay(**data)
    db.add(training_day)
    db.commit()
    db.refresh(training_day)
    return training_day


def update_training_day(db: Session, training_day: TrainingDay, training_day_in: TrainingDayUpdate) -> TrainingDay:
    data = training_day_in.model_dump(exclude_unset=True)
    training_plan_id = data.get("training_plan_id", training_day.training_plan_id)
    training_plan = db.get(TrainingPlan, training_plan_id)
    if training_plan is None:
        raise ValueError("Training plan not found")

    data["athlete_id"] = training_plan.athlete_id

    for field, value in data.items():
        setattr(training_day, field, value)

    db.add(training_day)
    db.commit()
    db.refresh(training_day)
    return training_day


def delete_training_day(db: Session, training_day: TrainingDay) -> None:
    db.delete(training_day)
    db.commit()
