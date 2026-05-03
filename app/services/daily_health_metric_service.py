from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.daily_health_metric import DailyHealthMetric
from app.schemas.daily_health_metric import HealthDailyMetricCreate, HealthDailyMetricUpdate


def get_health_metrics(db: Session) -> list[DailyHealthMetric]:
    statement = (
        select(DailyHealthMetric)
        .options(selectinload(DailyHealthMetric.athlete))
        .order_by(DailyHealthMetric.metric_date.desc(), DailyHealthMetric.id.desc())
    )
    return list(db.scalars(statement).all())


def get_health_metric(db: Session, metric_id: int) -> DailyHealthMetric | None:
    statement = (
        select(DailyHealthMetric)
        .where(DailyHealthMetric.id == metric_id)
        .options(selectinload(DailyHealthMetric.athlete))
    )
    return db.scalar(statement)


def get_health_metric_by_date(db: Session, athlete_id: int, metric_date: date) -> DailyHealthMetric | None:
    statement = (
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date == metric_date,
        )
        .options(selectinload(DailyHealthMetric.athlete))
    )
    return db.scalar(statement)


def list_health_metrics_for_athlete_range(
    db: Session,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> list[DailyHealthMetric]:
    statement = (
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date >= date_from,
            DailyHealthMetric.metric_date <= date_to,
        )
        .options(selectinload(DailyHealthMetric.athlete))
        .order_by(DailyHealthMetric.metric_date.asc(), DailyHealthMetric.id.asc())
    )
    return list(db.scalars(statement).all())


def create_or_update_daily_health_metric(
    db: Session,
    metric_in: HealthDailyMetricCreate,
) -> DailyHealthMetric:
    existing = get_health_metric_by_date(db, metric_in.athlete_id, metric_in.date)
    payload = metric_in.model_dump(by_alias=True)
    payload = _normalize_health_metric_payload(payload)

    if existing is None:
        metric = DailyHealthMetric(**payload)
        db.add(metric)
    else:
        metric = _apply_health_metric_payload(existing, payload)
        db.add(metric)

    db.commit()
    db.refresh(metric)
    return metric


def update_daily_health_metric(
    db: Session,
    metric: DailyHealthMetric,
    metric_in: HealthDailyMetricUpdate,
) -> DailyHealthMetric:
    payload = _normalize_health_metric_payload(metric_in.model_dump(exclude_unset=True))
    _apply_health_metric_payload(metric, payload)
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric


def _apply_health_metric_payload(metric: DailyHealthMetric, payload: dict[str, object]) -> DailyHealthMetric:
    for field, value in payload.items():
        setattr(metric, field, value)
    return metric


def _normalize_health_metric_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)

    sleep_duration = normalized.get("sleep_duration_minutes")
    sleep_hours = normalized.get("sleep_hours")
    if sleep_duration is not None and sleep_hours is None:
        normalized["sleep_hours"] = round(float(sleep_duration) / 60.0, 2)

    hrv_value = normalized.get("hrv_value")
    hrv_avg_ms = normalized.get("hrv_avg_ms")
    if hrv_value is not None and hrv_avg_ms is None:
        normalized["hrv_avg_ms"] = float(hrv_value)

    body_battery_morning = normalized.get("body_battery_morning")
    body_battery_start = normalized.get("body_battery_start")
    if body_battery_morning is not None and body_battery_start is None:
        normalized["body_battery_start"] = int(body_battery_morning)

    body_battery_max = normalized.get("body_battery_max")
    body_battery_end = normalized.get("body_battery_end")
    if body_battery_max is not None and body_battery_end is None:
        normalized["body_battery_end"] = int(body_battery_max)

    return normalized
