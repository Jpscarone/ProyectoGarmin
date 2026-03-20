from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.session_group import SessionGroup
from app.schemas.training_plan import TrainingPlanCreate, TrainingPlanUpdate


def get_training_plans(db: Session) -> list[TrainingPlan]:
    statement = (
        select(TrainingPlan)
        .options(selectinload(TrainingPlan.athlete), selectinload(TrainingPlan.goal))
        .order_by(TrainingPlan.start_date.desc(), TrainingPlan.id.desc())
    )
    return list(db.scalars(statement).all())


def get_training_plan(db: Session, training_plan_id: int) -> TrainingPlan | None:
    return db.get(TrainingPlan, training_plan_id)


def get_training_plan_detail(db: Session, training_plan_id: int) -> TrainingPlan | None:
    statement = (
        select(TrainingPlan)
        .where(TrainingPlan.id == training_plan_id)
        .options(
            selectinload(TrainingPlan.athlete),
            selectinload(TrainingPlan.goal),
            selectinload(TrainingPlan.training_days)
            .selectinload(TrainingDay.session_groups)
            .selectinload(SessionGroup.planned_sessions),
            selectinload(TrainingPlan.training_days)
            .selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.session_group),
            selectinload(TrainingPlan.training_days)
            .selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.planned_session_steps),
            selectinload(TrainingPlan.training_days)
            .selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.activity_match)
            .selectinload(ActivitySessionMatch.garmin_activity),
            selectinload(TrainingPlan.training_days)
            .selectinload(TrainingDay.planned_sessions)
            .selectinload(PlannedSession.analysis_reports),
            selectinload(TrainingPlan.training_days).selectinload(TrainingDay.analysis_reports),
        )
    )
    return db.scalar(statement)


def create_training_plan(db: Session, training_plan_in: TrainingPlanCreate) -> TrainingPlan:
    if training_plan_in.goal_id is not None:
        goal = db.get(Goal, training_plan_in.goal_id)
        if goal is None or goal.athlete_id != training_plan_in.athlete_id:
            raise ValueError("Selected goal does not belong to the selected athlete")

    training_plan = TrainingPlan(**training_plan_in.model_dump())
    db.add(training_plan)
    db.commit()
    db.refresh(training_plan)
    return training_plan


def update_training_plan(db: Session, training_plan: TrainingPlan, training_plan_in: TrainingPlanUpdate) -> TrainingPlan:
    data = training_plan_in.model_dump(exclude_unset=True)
    athlete_id = data.get("athlete_id", training_plan.athlete_id)
    goal_id = data.get("goal_id", training_plan.goal_id)

    if goal_id is not None:
        goal = db.get(Goal, goal_id)
        if goal is None or goal.athlete_id != athlete_id:
            raise ValueError("Selected goal does not belong to the selected athlete")

    for field, value in data.items():
        setattr(training_plan, field, value)

    db.add(training_plan)
    db.commit()
    db.refresh(training_plan)
    return training_plan


def delete_training_plan(db: Session, training_plan: TrainingPlan) -> None:
    db.delete(training_plan)
    db.commit()
