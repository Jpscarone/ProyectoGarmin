from __future__ import annotations

from datetime import date as date_type, datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthDailyMetricBase(BaseModel):
    athlete_id: int
    date: date_type = Field(alias="metric_date")
    sleep_duration_minutes: int | None = None
    sleep_score: int | None = None
    resting_hr: int | None = None
    hrv_value: float | None = None
    hrv_status: str | None = None
    stress_avg: int | None = None
    body_battery_morning: int | None = None
    body_battery_min: int | None = None
    body_battery_max: int | None = None
    training_load: float | None = None
    notes: str | None = None
    source: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class HealthDailyMetricCreate(HealthDailyMetricBase):
    pass


class HealthDailyMetricUpdate(BaseModel):
    sleep_duration_minutes: int | None = None
    sleep_score: int | None = None
    resting_hr: int | None = None
    hrv_value: float | None = None
    hrv_status: str | None = None
    stress_avg: int | None = None
    body_battery_morning: int | None = None
    body_battery_min: int | None = None
    body_battery_max: int | None = None
    training_load: float | None = None
    notes: str | None = None
    source: str | None = None


class HealthDailyMetricRead(HealthDailyMetricBase):
    id: int
    sleep_hours: float | None = None
    deep_sleep_min: int | None = None
    rem_sleep_min: int | None = None
    awake_count: int | None = None
    stress_max: int | None = None
    high_stress_duration_min: int | None = None
    body_battery_start: int | None = None
    body_battery_end: int | None = None
    hrv_avg_ms: float | None = None
    avg_daily_hr: int | None = None
    recovery_time_hours: float | None = None
    vo2max: float | None = None
    spo2_avg: float | None = None
    respiration_avg: float | None = None
    raw_health_json: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class HealthReadinessSummary(BaseModel):
    athlete_id: int
    reference_date: date_type
    sleep_avg_7d: float | None = None
    sleep_avg_14d: float | None = None
    resting_hr_avg_14d: float | None = None
    resting_hr_avg_3d: float | None = None
    resting_hr_delta_3d_vs_14d: float | None = None
    hrv_avg_14d: float | None = None
    hrv_avg_7d: float | None = None
    hrv_trend: str | None = None
    stress_avg_3d: float | None = None
    stress_avg_7d: float | None = None
    body_battery_morning_avg_3d: float | None = None
    body_battery_morning_avg_7d: float | None = None
    available_days_14d: int
    missing_days_14d: int


class HealthReadinessEvaluation(BaseModel):
    readiness_score: int | None
    readiness_status: str
    readiness_label: str
    main_limiter: str | None = None
    reasons: list[str] = Field(default_factory=list)
    recommendation: str
    data_quality: str
    data_quality_reasons: list[str] = Field(default_factory=list)


class HealthAIAnalysisResult(BaseModel):
    summary: str
    training_recommendation: str
    risk_level: str
    main_factors: list[str] = Field(default_factory=list)
    what_to_watch: list[str] = Field(default_factory=list)
    not_medical_advice: bool = True


DailyHealthMetricRead = HealthDailyMetricRead
