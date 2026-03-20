from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DailyHealthMetricRead(BaseModel):
    id: int
    athlete_id: int
    metric_date: date
    sleep_hours: float | None = None
    sleep_score: int | None = None
    deep_sleep_min: int | None = None
    rem_sleep_min: int | None = None
    awake_count: int | None = None
    stress_avg: int | None = None
    stress_max: int | None = None
    high_stress_duration_min: int | None = None
    body_battery_start: int | None = None
    body_battery_min: int | None = None
    body_battery_end: int | None = None
    hrv_status: str | None = None
    hrv_avg_ms: float | None = None
    resting_hr: int | None = None
    avg_daily_hr: int | None = None
    recovery_time_hours: float | None = None
    vo2max: float | None = None
    spo2_avg: float | None = None
    respiration_avg: float | None = None
    raw_health_json: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
