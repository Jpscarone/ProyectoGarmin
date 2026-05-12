from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_short_year_date(value: date | None) -> date | None:
    if value is None:
        return None
    if 0 < value.year < 100:
        return value.replace(year=2000 + value.year)
    return value


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

    @field_validator("event_date", mode="after")
    @classmethod
    def normalize_event_date(cls, value: date | None) -> date | None:
        return _normalize_short_year_date(value)


class TrainingPlanBase(BaseModel):
    athlete_id: int
    goal_id: int | None = None
    name: str
    sport_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    status: str | None = None

    @field_validator("start_date", "end_date", mode="after")
    @classmethod
    def normalize_plan_dates(cls, value: date | None) -> date | None:
        return _normalize_short_year_date(value)


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
