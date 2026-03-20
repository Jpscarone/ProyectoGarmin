from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.session_group import SessionGroup
from app.db.models.training_day import TrainingDay
from app.schemas.planned_session import PlannedSessionCreate, PlannedSessionUpdate


def get_planned_sessions(db: Session) -> list[PlannedSession]:
    statement = select(PlannedSession).order_by(PlannedSession.created_at.desc(), PlannedSession.id.desc())
    return list(db.scalars(statement).all())


def get_planned_session(db: Session, planned_session_id: int) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .where(PlannedSession.id == planned_session_id)
        .options(
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            selectinload(PlannedSession.session_group),
            selectinload(PlannedSession.planned_session_steps),
            selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity),
            selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.training_day),
        )
    )
    return db.scalar(statement)


def create_planned_session(db: Session, planned_session_in: PlannedSessionCreate) -> PlannedSession:
    training_day = db.get(TrainingDay, planned_session_in.training_day_id)
    if training_day is None:
        raise ValueError("Training day not found")

    data = planned_session_in.model_dump()
    session_group_id = data.get("session_group_id")
    if session_group_id is not None:
        session_group = db.get(SessionGroup, session_group_id)
        if session_group is None or session_group.training_day_id != training_day.id:
            raise ValueError("Selected session group does not belong to the selected training day")

    data["athlete_id"] = training_day.athlete_id

    planned_session = PlannedSession(**data)
    db.add(planned_session)
    db.commit()
    db.refresh(planned_session)
    return planned_session


def update_planned_session(
    db: Session,
    planned_session: PlannedSession,
    planned_session_in: PlannedSessionUpdate,
) -> PlannedSession:
    data = planned_session_in.model_dump(exclude_unset=True)
    training_day_id = data.get("training_day_id", planned_session.training_day_id)
    training_day = db.get(TrainingDay, training_day_id)
    if training_day is None:
        raise ValueError("Training day not found")

    session_group_id = data.get("session_group_id", planned_session.session_group_id)
    if session_group_id is not None:
        session_group = db.get(SessionGroup, session_group_id)
        if session_group is None or session_group.training_day_id != training_day.id:
            raise ValueError("Selected session group does not belong to the selected training day")

    data["athlete_id"] = training_day.athlete_id

    for field, value in data.items():
        setattr(planned_session, field, value)

    db.add(planned_session)
    db.commit()
    db.refresh(planned_session)
    return planned_session


def delete_planned_session(db: Session, planned_session: PlannedSession) -> None:
    db.delete(planned_session)
    db.commit()
