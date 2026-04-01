from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.schemas.planned_session_step import PlannedSessionStepCreate, PlannedSessionStepUpdate
from app.services.intensity_target_service import normalize_step_target_fields


def get_steps_for_session(db: Session, planned_session_id: int) -> list[PlannedSessionStep]:
    statement = (
        select(PlannedSessionStep)
        .where(PlannedSessionStep.planned_session_id == planned_session_id)
        .order_by(PlannedSessionStep.step_order.asc(), PlannedSessionStep.id.asc())
    )
    return list(db.scalars(statement).all())


def get_step(db: Session, step_id: int) -> PlannedSessionStep | None:
    return db.get(PlannedSessionStep, step_id)


def create_step(db: Session, step_in: PlannedSessionStepCreate) -> PlannedSessionStep:
    planned_session = db.get(PlannedSession, step_in.planned_session_id)
    if planned_session is None:
        raise ValueError("Planned session not found")

    data = normalize_step_target_fields(step_in.model_dump(), planned_session.athlete)
    step = PlannedSessionStep(**data)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def update_step(db: Session, step: PlannedSessionStep, step_in: PlannedSessionStepUpdate) -> PlannedSessionStep:
    data = step_in.model_dump(exclude_unset=True)

    planned_session_id = data.get("planned_session_id", step.planned_session_id)
    planned_session = db.get(PlannedSession, planned_session_id)
    if planned_session is None:
        raise ValueError("Planned session not found")

    data = normalize_step_target_fields(data, planned_session.athlete)

    for field, value in data.items():
        setattr(step, field, value)

    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def delete_step(db: Session, step: PlannedSessionStep) -> None:
    db.delete(step)
    db.commit()


def replace_steps_for_session(
    db: Session,
    planned_session: PlannedSession,
    steps_in: list[PlannedSessionStepCreate],
) -> list[PlannedSessionStep]:
    existing_steps = get_steps_for_session(db, planned_session.id)
    for existing_step in existing_steps:
        db.delete(existing_step)

    created_steps: list[PlannedSessionStep] = []
    for step_in in steps_in:
        data = normalize_step_target_fields(step_in.model_dump(), planned_session.athlete)
        step = PlannedSessionStep(**data)
        db.add(step)
        created_steps.append(step)

    db.commit()

    for step in created_steps:
        db.refresh(step)

    return created_steps
