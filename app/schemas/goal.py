from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class GoalBase(BaseModel):
    athlete_id: int
    name: str
    sport_type: str | None = None
    event_type: str | None = None
    event_date: date | None = None
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    priority: str | None = None
    location_name: str | None = None
    notes: str | None = None
    status: str | None = None


class GoalCreate(GoalBase):
    pass


class GoalUpdate(BaseModel):
    athlete_id: int | None = None
    name: str | None = None
    sport_type: str | None = None
    event_type: str | None = None
    event_date: date | None = None
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    priority: str | None = None
    location_name: str | None = None
    notes: str | None = None
    status: str | None = None


class GoalRead(GoalBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
