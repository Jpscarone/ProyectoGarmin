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
from app.services.intensity_target_service import normalize_session_target_fields
from app.services.session_completion_service import clear_strength_session_completion, mark_strength_session_completed


def _normalize_sport_specific_fields(data: dict) -> dict:
    sport_type = str(data.get("sport_type") or "").strip().lower()
    if sport_type != "strength":
        return data

    data["expected_distance_km"] = None
    data["expected_elevation_gain_m"] = None
    data["target_type"] = None
    data["target_hr_zone"] = None
    data["target_pace_zone"] = None
    data["target_power_zone"] = None
    data["target_rpe_zone"] = None
    return data


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
    data = normalize_session_target_fields(data)
    data = _normalize_sport_specific_fields(data)

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
    data = normalize_session_target_fields(data)
    data = _normalize_sport_specific_fields(data)

    for field, value in data.items():
        setattr(planned_session, field, value)

    db.add(planned_session)
    db.commit()
    db.refresh(planned_session)
    return planned_session


def delete_planned_session(db: Session, planned_session: PlannedSession) -> None:
    db.delete(planned_session)
    db.commit()


def complete_strength_session_manually(
    db: Session,
    planned_session: PlannedSession,
    *,
    duration_sec: int | None,
    strength_rpe: int | None,
    strength_focus: str | None,
    notes: str | None,
) -> PlannedSession:
    mark_strength_session_completed(
        planned_session,
        duration_sec=duration_sec,
        strength_rpe=strength_rpe,
        strength_focus=strength_focus,
        notes=notes,
    )
    db.add(planned_session)
    db.commit()
    db.refresh(planned_session)
    return planned_session


def clear_strength_session_manual_completion(db: Session, planned_session: PlannedSession) -> PlannedSession:
    clear_strength_session_completion(planned_session)
    db.add(planned_session)
    db.commit()
    db.refresh(planned_session)
    return planned_session
