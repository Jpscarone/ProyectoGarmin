from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.goal import Goal
from app.schemas.goal import GoalCreate, GoalUpdate


def get_goals(db: Session) -> list[Goal]:
    statement = select(Goal).options(selectinload(Goal.athlete)).order_by(Goal.event_date.asc(), Goal.id.desc())
    return list(db.scalars(statement).all())


def get_goal(db: Session, goal_id: int) -> Goal | None:
    return db.get(Goal, goal_id)


def create_goal(db: Session, goal_in: GoalCreate) -> Goal:
    goal = Goal(**goal_in.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(db: Session, goal: Goal, goal_in: GoalUpdate) -> Goal:
    for field, value in goal_in.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)

    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def delete_goal(db: Session, goal: Goal) -> None:
    db.delete(goal)
    db.commit()
