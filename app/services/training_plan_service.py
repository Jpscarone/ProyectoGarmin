from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.session_group import SessionGroup
from app.schemas.training_plan import TrainingPlanCreate, TrainingPlanUpdate


TRAINING_PLAN_STATUS_DRAFT = "draft"
TRAINING_PLAN_STATUS_ACTIVE = "active"
TRAINING_PLAN_STATUS_COMPLETED = "completed"
TRAINING_PLAN_STATUS_ARCHIVED = "archived"
TRAINING_PLAN_STATUS_CANCELLED = "cancelled"

TRAINING_PLAN_STATUSES = {
    TRAINING_PLAN_STATUS_DRAFT,
    TRAINING_PLAN_STATUS_ACTIVE,
    TRAINING_PLAN_STATUS_COMPLETED,
    TRAINING_PLAN_STATUS_ARCHIVED,
    TRAINING_PLAN_STATUS_CANCELLED,
}


def normalize_training_plan_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in TRAINING_PLAN_STATUSES:
        return normalized
    return TRAINING_PLAN_STATUS_DRAFT


def auto_complete_expired_training_plans(db: Session, today: date | None = None) -> int:
    reference_date = today or date.today()
    expired_plans = list(
        db.scalars(
            select(TrainingPlan).where(
                TrainingPlan.status == TRAINING_PLAN_STATUS_ACTIVE,
                TrainingPlan.end_date.is_not(None),
                TrainingPlan.end_date < reference_date,
            )
        ).all()
    )
    for plan in expired_plans:
        plan.status = TRAINING_PLAN_STATUS_COMPLETED
        db.add(plan)
    if expired_plans:
        db.commit()
    return len(expired_plans)


def get_training_plans(db: Session) -> list[TrainingPlan]:
    statement = (
        select(TrainingPlan)
        .options(selectinload(TrainingPlan.athlete), selectinload(TrainingPlan.goal), selectinload(TrainingPlan.goals))
        .order_by(TrainingPlan.start_date.desc(), TrainingPlan.id.desc())
    )
    return list(db.scalars(statement).all())


def get_training_plans_for_athlete(db: Session, athlete_id: int) -> list[TrainingPlan]:
    statement = (
        select(TrainingPlan)
        .where(TrainingPlan.athlete_id == athlete_id)
        .options(selectinload(TrainingPlan.athlete), selectinload(TrainingPlan.goal), selectinload(TrainingPlan.goals))
        .order_by(TrainingPlan.start_date.desc(), TrainingPlan.id.desc())
    )
    return list(db.scalars(statement).all())


def select_default_training_plan(db: Session, athlete_id: int | None = None, today: date | None = None) -> TrainingPlan | None:
    reference_date = today or date.today()
    statement = select(TrainingPlan).options(selectinload(TrainingPlan.athlete), selectinload(TrainingPlan.goal))
    if athlete_id is not None:
        statement = statement.where(TrainingPlan.athlete_id == athlete_id)
    plans = list(db.scalars(statement).all())
    if not plans:
        return None

    active_current = [
        plan
        for plan in plans
        if normalize_training_plan_status(plan.status) == TRAINING_PLAN_STATUS_ACTIVE
        and (plan.start_date is None or plan.start_date <= reference_date)
        and (plan.end_date is None or plan.end_date >= reference_date)
    ]
    if active_current:
        return sorted(active_current, key=lambda plan: (plan.start_date or date.min, plan.id), reverse=True)[0]

    active_any = [plan for plan in plans if normalize_training_plan_status(plan.status) == TRAINING_PLAN_STATUS_ACTIVE]
    if active_any:
        return sorted(active_any, key=lambda plan: (plan.start_date or date.min, plan.id), reverse=True)[0]

    completed = [plan for plan in plans if normalize_training_plan_status(plan.status) == TRAINING_PLAN_STATUS_COMPLETED]
    if completed:
        return sorted(completed, key=lambda plan: (plan.end_date or plan.start_date or date.min, plan.id), reverse=True)[0]

    return sorted(plans, key=lambda plan: (plan.start_date or date.min, plan.id), reverse=True)[0]


def get_training_plan(db: Session, training_plan_id: int) -> TrainingPlan | None:
    return db.get(TrainingPlan, training_plan_id)


def get_training_plan_detail(db: Session, training_plan_id: int) -> TrainingPlan | None:
    statement = (
        select(TrainingPlan)
        .where(TrainingPlan.id == training_plan_id)
        .options(
            selectinload(TrainingPlan.athlete),
            selectinload(TrainingPlan.goal),
            selectinload(TrainingPlan.goals),
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
    payload = training_plan_in.model_dump(exclude={"primary_goal", "secondary_goals"})
    payload["status"] = normalize_training_plan_status(payload.get("status"))
    if payload.get("goal_id") is not None:
        goal = db.get(Goal, payload["goal_id"])
        if goal is None or goal.athlete_id != training_plan_in.athlete_id:
            raise ValueError("Selected goal does not belong to the selected athlete")

    training_plan = TrainingPlan(**payload)
    db.add(training_plan)
    db.flush()
    _sync_plan_goals(db, training_plan, training_plan_in.athlete_id, training_plan_in.primary_goal, training_plan_in.secondary_goals)
    db.commit()
    db.refresh(training_plan)
    return training_plan


def update_training_plan(db: Session, training_plan: TrainingPlan, training_plan_in: TrainingPlanUpdate) -> TrainingPlan:
    data = training_plan_in.model_dump(exclude_unset=True, exclude={"primary_goal", "secondary_goals"})
    if "status" in data:
        data["status"] = normalize_training_plan_status(data.get("status"))
    athlete_id = data.get("athlete_id", training_plan.athlete_id)
    goal_id = data.get("goal_id", training_plan.goal_id)

    if goal_id is not None:
        goal = db.get(Goal, goal_id)
        if goal is None or goal.athlete_id != athlete_id:
            raise ValueError("Selected goal does not belong to the selected athlete")

    for field, value in data.items():
        setattr(training_plan, field, value)

    db.add(training_plan)
    if "primary_goal" in training_plan_in.model_fields_set or "secondary_goals" in training_plan_in.model_fields_set:
        _sync_plan_goals(
            db,
            training_plan,
            athlete_id,
            training_plan_in.primary_goal,
            training_plan_in.secondary_goals or [],
        )
    db.commit()
    db.refresh(training_plan)
    return training_plan


def delete_training_plan(db: Session, training_plan: TrainingPlan) -> None:
    db.delete(training_plan)
    db.commit()


def _sync_plan_goals(
    db: Session,
    training_plan: TrainingPlan,
    athlete_id: int,
    primary_goal_data,
    secondary_goal_data_list,
) -> None:
    existing_goals = {goal.id: goal for goal in training_plan.goals if goal.id is not None}
    keep_goal_ids: set[int] = set()
    primary_goal_id: int | None = None

    if primary_goal_data and _goal_has_content(primary_goal_data):
        primary_goal = _upsert_goal(
            db,
            existing_goal=existing_goals.get(primary_goal_data.id) if primary_goal_data.id else None,
            athlete_id=athlete_id,
            training_plan_id=training_plan.id,
            goal_role="primary",
            goal_data=primary_goal_data,
        )
        primary_goal_id = primary_goal.id
        keep_goal_ids.add(primary_goal.id)

    for secondary_goal_data in secondary_goal_data_list or []:
        if not _goal_has_content(secondary_goal_data):
            continue
        secondary_goal = _upsert_goal(
            db,
            existing_goal=existing_goals.get(secondary_goal_data.id) if secondary_goal_data.id else None,
            athlete_id=athlete_id,
            training_plan_id=training_plan.id,
            goal_role="secondary",
            goal_data=secondary_goal_data,
        )
        keep_goal_ids.add(secondary_goal.id)

    for goal in list(training_plan.goals):
        if goal.id not in keep_goal_ids:
            db.delete(goal)

    training_plan.goal_id = primary_goal_id


def _upsert_goal(db: Session, *, existing_goal: Goal | None, athlete_id: int, training_plan_id: int, goal_role: str, goal_data) -> Goal:
    goal = existing_goal or Goal(athlete_id=athlete_id, training_plan_id=training_plan_id)
    goal.athlete_id = athlete_id
    goal.training_plan_id = training_plan_id
    goal.goal_role = goal_role
    goal.name = (goal_data.name or "").strip() or ("Objetivo principal" if goal_role == "primary" else "Objetivo secundario")
    goal.sport_type = goal_data.sport_type
    goal.event_date = goal_data.event_date
    goal.distance_km = goal_data.distance_km
    goal.elevation_gain_m = goal_data.elevation_gain_m
    goal.location_name = goal_data.location_name
    goal.priority = goal_data.priority
    goal.notes = goal_data.notes
    db.add(goal)
    db.flush()
    return goal


def _goal_has_content(goal_data) -> bool:
    return any(
        [
            getattr(goal_data, "name", None),
            getattr(goal_data, "sport_type", None),
            getattr(goal_data, "event_date", None),
            getattr(goal_data, "distance_km", None) is not None,
            getattr(goal_data, "elevation_gain_m", None) is not None,
            getattr(goal_data, "location_name", None),
            getattr(goal_data, "priority", None),
            getattr(goal_data, "notes", None),
        ]
    )
