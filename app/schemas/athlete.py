from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AthleteBase(BaseModel):
    name: str
    height_cm: float | None = None
    weight_kg: float | None = None
    max_hr: int | None = None
    resting_hr: int | None = None
    lactate_threshold_hr: int | None = None
    running_threshold_pace_sec_km: int | None = None
    cycling_ftp: int | None = None
    vo2max: float | None = None
    notes: str | None = None


class AthleteCreate(AthleteBase):
    pass


class AthleteUpdate(BaseModel):
    name: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    max_hr: int | None = None
    resting_hr: int | None = None
    lactate_threshold_hr: int | None = None
    running_threshold_pace_sec_km: int | None = None
    cycling_ftp: int | None = None
    vo2max: float | None = None
    notes: str | None = None


class AthleteRead(AthleteBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
