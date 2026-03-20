from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, ConfigDict


class PlannedSessionBase(BaseModel):
    training_day_id: int
    athlete_id: int | None = None
    session_group_id: int | None = None
    sport_type: str | None = None
    discipline_variant: str | None = None
    name: str
    description_text: str | None = None
    session_type: str | None = None
    session_order: int = 1
    planned_start_time: time | None = None
    expected_duration_min: int | None = None
    expected_distance_km: float | None = None
    expected_elevation_gain_m: float | None = None
    target_hr_zone: str | None = None
    target_power_zone: str | None = None
    target_notes: str | None = None
    is_key_session: bool = False


class PlannedSessionCreate(PlannedSessionBase):
    pass


class PlannedSessionUpdate(BaseModel):
    training_day_id: int | None = None
    athlete_id: int | None = None
    session_group_id: int | None = None
    sport_type: str | None = None
    discipline_variant: str | None = None
    name: str | None = None
    description_text: str | None = None
    session_type: str | None = None
    session_order: int | None = None
    planned_start_time: time | None = None
    expected_duration_min: int | None = None
    expected_distance_km: float | None = None
    expected_elevation_gain_m: float | None = None
    target_hr_zone: str | None = None
    target_power_zone: str | None = None
    target_notes: str | None = None
    is_key_session: bool | None = None


class PlannedSessionRead(PlannedSessionBase):
    id: int
    athlete_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
