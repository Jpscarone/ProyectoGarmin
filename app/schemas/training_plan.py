from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TrainingPlanBase(BaseModel):
    athlete_id: int
    goal_id: int | None = None
    name: str
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    status: str | None = None


class TrainingPlanCreate(TrainingPlanBase):
    pass


class TrainingPlanUpdate(BaseModel):
    athlete_id: int | None = None
    goal_id: int | None = None
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    status: str | None = None


class TrainingPlanRead(TrainingPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
