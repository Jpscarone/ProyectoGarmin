from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class PlanGoalInput(BaseModel):
    id: int | None = None
    name: str | None = None
    sport_type: str | None = None
    event_date: date | None = None
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    location_name: str | None = None
    priority: str | None = None
    notes: str | None = None


class TrainingPlanBase(BaseModel):
    athlete_id: int
    goal_id: int | None = None
    name: str
    sport_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    status: str | None = None


class TrainingPlanCreate(TrainingPlanBase):
    primary_goal: PlanGoalInput | None = None
    secondary_goals: list[PlanGoalInput] = []


class TrainingPlanUpdate(BaseModel):
    athlete_id: int | None = None
    goal_id: int | None = None
    name: str | None = None
    sport_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    status: str | None = None
    primary_goal: PlanGoalInput | None = None
    secondary_goals: list[PlanGoalInput] | None = None


class TrainingPlanRead(TrainingPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
