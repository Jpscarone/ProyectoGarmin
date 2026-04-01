from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


SUPPORTED_STEP_TYPES = {
    "warmup",
    "work",
    "recovery",
    "cooldown",
    "steady",
    "drills",
    "strides",
    "swim_repeat",
    "transition",
}

SUPPORTED_TARGET_TYPES = {
    "hr",
    "pace",
    "power",
    "rpe",
}


class PlannedSessionStepBase(BaseModel):
    planned_session_id: int
    step_order: int = 1
    step_type: str
    repeat_count: int | None = None
    duration_sec: int | None = None
    distance_m: int | None = None
    target_type: str | None = None
    target_hr_zone: str | None = None
    target_hr_min: int | None = None
    target_hr_max: int | None = None
    target_power_zone: str | None = None
    target_power_min: int | None = None
    target_power_max: int | None = None
    target_pace_zone: str | None = None
    target_pace_min_sec_km: int | None = None
    target_pace_max_sec_km: int | None = None
    target_rpe_zone: str | None = None
    target_cadence_min: int | None = None
    target_cadence_max: int | None = None
    target_notes: str | None = None

    @field_validator("step_type")
    @classmethod
    def validate_step_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_STEP_TYPES:
            raise ValueError(f"Unsupported step_type: {value}")
        return normalized

    @field_validator("target_type")
    @classmethod
    def validate_target_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_TARGET_TYPES:
            raise ValueError(f"Unsupported target_type: {value}")
        return normalized


class PlannedSessionStepCreate(PlannedSessionStepBase):
    pass


class PlannedSessionStepUpdate(BaseModel):
    planned_session_id: int | None = None
    step_order: int | None = None
    step_type: str | None = None
    repeat_count: int | None = None
    duration_sec: int | None = None
    distance_m: int | None = None
    target_type: str | None = None
    target_hr_zone: str | None = None
    target_hr_min: int | None = None
    target_hr_max: int | None = None
    target_power_zone: str | None = None
    target_power_min: int | None = None
    target_power_max: int | None = None
    target_pace_zone: str | None = None
    target_pace_min_sec_km: int | None = None
    target_pace_max_sec_km: int | None = None
    target_rpe_zone: str | None = None
    target_cadence_min: int | None = None
    target_cadence_max: int | None = None
    target_notes: str | None = None

    @field_validator("step_type")
    @classmethod
    def validate_step_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_STEP_TYPES:
            raise ValueError(f"Unsupported step_type: {value}")
        return normalized

    @field_validator("target_type")
    @classmethod
    def validate_target_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_TARGET_TYPES:
            raise ValueError(f"Unsupported target_type: {value}")
        return normalized


class PlannedSessionStepRead(PlannedSessionStepBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
