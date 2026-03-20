from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.session_group import SessionGroup
from app.db.models.training_day import TrainingDay
from app.schemas.session_group import SessionGroupCreate, SessionGroupUpdate


def get_groups_for_day(db: Session, training_day_id: int) -> list[SessionGroup]:
    statement = (
        select(SessionGroup)
        .where(SessionGroup.training_day_id == training_day_id)
        .options(selectinload(SessionGroup.planned_sessions))
        .order_by(SessionGroup.group_order.asc(), SessionGroup.id.asc())
    )
    return list(db.scalars(statement).all())


def get_group(db: Session, group_id: int) -> SessionGroup | None:
    statement = (
        select(SessionGroup)
        .where(SessionGroup.id == group_id)
        .options(selectinload(SessionGroup.training_day), selectinload(SessionGroup.planned_sessions))
    )
    return db.scalar(statement)


def create_group(db: Session, group_in: SessionGroupCreate) -> SessionGroup:
    training_day = db.get(TrainingDay, group_in.training_day_id)
    if training_day is None:
        raise ValueError("Training day not found")

    group = SessionGroup(**group_in.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def create_inline_group(
    db: Session,
    *,
    training_day_id: int,
    name: str,
    group_type: str | None = None,
    notes: str | None = None,
) -> SessionGroup:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("El nombre del grupo es obligatorio.")

    return create_group(
        db,
        SessionGroupCreate(
            training_day_id=training_day_id,
            name=normalized_name,
            group_type=group_type or None,
            group_order=_next_group_order(db, training_day_id),
            notes=notes or None,
        ),
    )


def update_group(db: Session, group: SessionGroup, group_in: SessionGroupUpdate) -> SessionGroup:
    data = group_in.model_dump(exclude_unset=True)
    training_day_id = data.get("training_day_id", group.training_day_id)
    training_day = db.get(TrainingDay, training_day_id)
    if training_day is None:
        raise ValueError("Training day not found")

    for field, value in data.items():
        setattr(group, field, value)

    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def delete_group(db: Session, group: SessionGroup) -> None:
    for planned_session in group.planned_sessions:
        planned_session.session_group_id = None

    db.delete(group)
    db.commit()


def _next_group_order(db: Session, training_day_id: int) -> int:
    groups = get_groups_for_day(db, training_day_id)
    if not groups:
        return 1
    return max(group.group_order for group in groups) + 1
