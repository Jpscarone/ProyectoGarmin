from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TrainingDayBase(BaseModel):
    training_plan_id: int
    athlete_id: int | None = None
    day_date: date
    day_notes: str | None = None
    day_type: str | None = None


class TrainingDayCreate(TrainingDayBase):
    pass


class TrainingDayUpdate(BaseModel):
    training_plan_id: int | None = None
    athlete_id: int | None = None
    day_date: date | None = None
    day_notes: str | None = None
    day_type: str | None = None


class TrainingDayRead(TrainingDayBase):
    id: int
    athlete_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
