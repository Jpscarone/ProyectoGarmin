from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GarminActivityLapRead(BaseModel):
    id: int
    garmin_activity_id_fk: int
    lap_number: int
    lap_type: str | None = None
    start_time: datetime | None = None
    duration_sec: int | None = None
    moving_duration_sec: int | None = None
    distance_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_power: int | None = None
    max_power: int | None = None
    avg_speed_mps: float | None = None
    avg_pace_sec_km: float | None = None
    avg_cadence: float | None = None
    max_cadence: float | None = None
    stroke_count: int | None = None
    swolf: int | None = None
    raw_lap_json: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GarminActivityRead(BaseModel):
    id: int
    athlete_id: int
    garmin_activity_id: int
    activity_name: str | None = None
    sport_type: str | None = None
    discipline_variant: str | None = None
    is_multisport: bool
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_sec: int | None = None
    moving_duration_sec: int | None = None
    distance_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_power: int | None = None
    max_power: int | None = None
    normalized_power: int | None = None
    avg_speed_mps: float | None = None
    max_speed_mps: float | None = None
    avg_pace_sec_km: float | None = None
    avg_cadence: float | None = None
    max_cadence: float | None = None
    training_effect_aerobic: float | None = None
    training_effect_anaerobic: float | None = None
    training_load: float | None = None
    calories: float | None = None
    avg_temperature_c: float | None = None
    start_lat: float | None = None
    start_lon: float | None = None
    device_name: str | None = None
    raw_summary_json: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GarminActivityDetailRead(GarminActivityRead):
    laps: list[GarminActivityLapRead] = []
